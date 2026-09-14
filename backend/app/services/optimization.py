"""Module 11 — multi-objective optimization. The project's core research
contribution: given a vehicle at a gate, recommend a parking lot by
minimizing a weighted, normalized objective over risk-adjusted PREDICTED
state -- never by any single raw signal alone.

    J = w1*WaitingTime + w2*QueueCost + w3*SearchTravel
      + w4*UtilizationImbalance + w5*OverflowPenalty

Every term is normalized to [0, 1] by dividing by the max raw value across
this call's *feasible* candidates (0 if that max is 0) -- a simple, documented
normalization scheme, not a statistically validated one. WaitingTime is
identical across every candidate for a single gate (queueing to enter the
campus doesn't depend on which lot you're then routed to) -- it still
matters when comparing calls/profiles, just not for ranking within one call.

Feasibility is checked BEFORE scoring, using a single reused mechanism:
Module 6's NavigationService already excludes closed gates/lots/roads from
its routable graph, so `find_route` raising NoFeasibleRouteError is exactly
"no way to legally reach this lot" (closed gate, closed lot, or a blocked
road along every path). Separately rejected: a "restricted" lot/gate
(navigation only filters "closed"), and a lot with zero currently-available
capacity (a route existing doesn't mean there's room). A cheaper-looking
infeasible candidate is never scored, let alone returned -- see
`_generate_candidates`.

Failure handling:
- A candidate's prediction unavailable/stale -> `_historical_average_fallback`
  (a live mean of that lot's own recent observations -- not Module 9's
  trained pipeline, just enough signal to keep scoring possible) -> if that
  also has nothing, the lot's current occupancy_pct is the last resort.
  Every candidate's `prediction_source` says which of the three it used.
- Scoring the whole candidate set exceeds `TIME_LIMIT_SECONDS` (default 2s)
  -> abort and fall back to Module 8's NearestAvailableLotStrategy logic
  (shortest travel time among feasible candidates), flagged in the result
  as `used_fallback="time_limit_exceeded"`.
- No feasible candidate at all -> a normal, documented "overflow" result
  (`feasible=False`, a `reason`), never an exception.

Deterministic for identical inputs (candidates are always considered in
lot_id order, ties broken by lot_id). Floating-point J values may differ in
their last few decimal digits across platforms/BLAS versions; ranking
stability is guaranteed only up to a 1e-9 tolerance (`J_TOLERANCE`), not
bit-identical output.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingestion import Observation
from app.repositories.campus_config import CampusConfigRepository
from app.repositories.twin import TwinRepository
from app.services.campus_config import CampusNotFoundError
from app.services.navigation import DRIVE, NavigationService, NoFeasibleRouteError
from app.services.prediction import DATA_STALE, INTELLIGENCE_UNAVAILABLE, PredictionService
from app.services.risk import RiskEngine

TIME_LIMIT_SECONDS = 2.0
J_TOLERANCE = 1e-9
PREDICTION_HORIZON_MINUTES = 15

PROFILES: dict[str, dict[str, float]] = {
    # Minimize how long the driver spends getting parked at all: gate wait
    # and the drive to the lot dominate.
    "P1_MIN_WAITING": {"w1": 0.40, "w2": 0.15, "w3": 0.35, "w4": 0.05, "w5": 0.05},
    # No single concern dominates.
    "P2_BALANCED": {"w1": 0.20, "w2": 0.20, "w3": 0.20, "w4": 0.20, "w5": 0.20},
    # Spread load across the campus and avoid overflow, even at the cost
    # of a longer wait/drive for any one vehicle.
    "P3_MAX_UTILIZATION": {"w1": 0.05, "w2": 0.15, "w3": 0.05, "w4": 0.35, "w5": 0.40},
}
DEFAULT_PROFILE = "P2_BALANCED"

STRATEGIES = ("first_available", "nearest_available", "prediction_only", "optimizer")


@dataclass
class ObjectiveTerms:
    waiting_time_raw: float
    queue_cost_raw: float
    search_travel_raw: float
    utilization_imbalance_raw: float
    overflow_penalty_raw: float
    waiting_time_norm: float = 0.0
    queue_cost_norm: float = 0.0
    search_travel_norm: float = 0.0
    utilization_imbalance_norm: float = 0.0
    overflow_penalty_norm: float = 0.0


@dataclass
class CandidateEvaluation:
    lot_id: str
    feasible: bool
    infeasible_reason: str | None
    predicted_occupancy_pct: float | None = None
    prediction_source: str | None = None  # "model" | "historical_average_fallback" | "current_state_fallback"
    travel_time_s: float | None = None
    travel_distance_m: float | None = None
    terms: ObjectiveTerms | None = None
    objective_j: float | None = None


@dataclass
class RecommendationResult:
    campus_id: str
    gate_id: str
    profile: str
    weights: dict[str, float]
    generated_at: datetime
    feasible: bool
    best: CandidateEvaluation | None
    alternatives: list[CandidateEvaluation]
    all_candidates: list[CandidateEvaluation]
    used_fallback: str | None = None
    reason: str | None = None


class GateNotFoundError(Exception):
    def __init__(self, campus_id: str, gate_id: str) -> None:
        self.campus_id = campus_id
        self.gate_id = gate_id
        super().__init__(f"gate {gate_id!r} not found on campus {campus_id!r}")


class OptimizationEngine:
    def __init__(
        self,
        prediction_service: PredictionService,
        risk_engine: RiskEngine | None = None,
        config_repository: CampusConfigRepository | None = None,
        twin_repository: TwinRepository | None = None,
        navigation_service: NavigationService | None = None,
    ) -> None:
        self._prediction = prediction_service
        self._risk = risk_engine or RiskEngine(prediction_service)
        self._config = config_repository or CampusConfigRepository()
        self._twin = twin_repository or TwinRepository()
        self._navigation = navigation_service or NavigationService()

    # -- public API -------------------------------------------------------

    async def recommend(
        self, session: AsyncSession, campus_id: str, gate_id: str, profile: str = DEFAULT_PROFILE
    ) -> RecommendationResult:
        if profile not in PROFILES:
            raise ValueError(f"profile must be one of {sorted(PROFILES)}, got {profile!r}")
        weights = PROFILES[profile]

        await self._require_campus_and_gate(session, campus_id, gate_id)
        candidates = await self._generate_candidates(session, campus_id, gate_id)
        feasible = [c for c in candidates if c.feasible]

        if not feasible:
            return RecommendationResult(
                campus_id=campus_id, gate_id=gate_id, profile=profile, weights=weights,
                generated_at=datetime.now(timezone.utc), feasible=False, best=None, alternatives=[],
                all_candidates=candidates,
                reason="no feasible parking lot: every lot is closed, restricted, full, or unreachable "
                "from this gate",
            )

        started = time.monotonic()
        scored = await self._score_candidates(session, campus_id, gate_id, feasible, weights, started)
        if scored is None:
            # Time limit exceeded mid-scoring -- fall back to nearest-available
            # among the feasible candidates already gathered.
            nearest = min(feasible, key=lambda c: (c.travel_time_s if c.travel_time_s is not None else float("inf"), c.lot_id))
            return RecommendationResult(
                campus_id=campus_id, gate_id=gate_id, profile=profile, weights=weights,
                generated_at=datetime.now(timezone.utc), feasible=True, best=nearest,
                alternatives=[c for c in feasible if c.lot_id != nearest.lot_id],
                all_candidates=candidates, used_fallback="time_limit_exceeded",
                reason=f"optimization exceeded the {TIME_LIMIT_SECONDS}s time limit; "
                "fell back to nearest-available",
            )

        scored.sort(key=lambda c: (round(c.objective_j / J_TOLERANCE), c.lot_id))
        best, *rest = scored
        infeasible = [c for c in candidates if not c.feasible]
        return RecommendationResult(
            campus_id=campus_id, gate_id=gate_id, profile=profile, weights=weights,
            generated_at=datetime.now(timezone.utc), feasible=True, best=best, alternatives=rest,
            all_candidates=scored + infeasible,
        )

    async def recommend_baseline(
        self, session: AsyncSession, campus_id: str, gate_id: str, strategy: str
    ) -> RecommendationResult:
        """B1/B2/B3 comparison strategies, sharing the exact same
        feasibility filter as the real optimizer -- a cheaper infeasible
        candidate is never returned by these either."""

        if strategy not in ("first_available", "nearest_available", "prediction_only"):
            raise ValueError(f"strategy must be one of first_available/nearest_available/prediction_only, "
                              f"got {strategy!r}")

        await self._require_campus_and_gate(session, campus_id, gate_id)
        candidates = await self._generate_candidates(session, campus_id, gate_id)
        feasible = [c for c in candidates if c.feasible]
        if not feasible:
            return RecommendationResult(
                campus_id=campus_id, gate_id=gate_id, profile=strategy, weights={},
                generated_at=datetime.now(timezone.utc), feasible=False, best=None, alternatives=[],
                all_candidates=candidates, reason="no feasible parking lot",
            )

        if strategy == "first_available":
            best = min(feasible, key=lambda c: c.lot_id)
        elif strategy == "nearest_available":
            best = min(feasible, key=lambda c: (c.travel_time_s if c.travel_time_s is not None else float("inf"),
                                                  c.lot_id))
        else:  # prediction_only -- B3, fully implemented against Module 9's real predictions
            for c in feasible:
                c.predicted_occupancy_pct, c.prediction_source = await self._predicted_occupancy_pct(
                    session, campus_id, c.lot_id
                )
            best = min(
                feasible,
                key=lambda c: (c.predicted_occupancy_pct if c.predicted_occupancy_pct is not None else float("inf"),
                                c.lot_id),
            )

        return RecommendationResult(
            campus_id=campus_id, gate_id=gate_id, profile=strategy, weights={},
            generated_at=datetime.now(timezone.utc), feasible=True, best=best,
            alternatives=[c for c in feasible if c.lot_id != best.lot_id], all_candidates=candidates,
        )

    async def compare(self, session: AsyncSession, campus_id: str, gate_id: str) -> dict[str, RecommendationResult]:
        """Runs all four strategies (B1, B2, B3, and the real optimizer)
        against the same live moment, for inspection/testing -- a live,
        single-shot comparison, not Module 8's simulated multi-seed
        ExperimentRunner (a different concern: that compares SIMULATED
        scenario runs; this compares one real recommendation)."""

        return {
            "first_available": await self.recommend_baseline(session, campus_id, gate_id, "first_available"),
            "nearest_available": await self.recommend_baseline(session, campus_id, gate_id, "nearest_available"),
            "prediction_only": await self.recommend_baseline(session, campus_id, gate_id, "prediction_only"),
            "optimizer": await self.recommend(session, campus_id, gate_id),
        }

    # -- internals ----------------------------------------------------------

    async def _require_campus_and_gate(self, session: AsyncSession, campus_id: str, gate_id: str) -> None:
        campus = await self._config.get_campus(session, campus_id)
        if campus is None:
            raise CampusNotFoundError(campus_id)
        gate_state = await self._twin.get_gate_state(session, gate_id)
        if gate_state is None or gate_state.campus_id != campus_id:
            raise GateNotFoundError(campus_id, gate_id)

    async def _generate_candidates(
        self, session: AsyncSession, campus_id: str, gate_id: str
    ) -> list[CandidateEvaluation]:
        lots = sorted(await self._config.list_parking_lots(session, campus_id), key=lambda lot: lot.parking_lot_id)
        gate_state = await self._twin.get_gate_state(session, gate_id)

        candidates: list[CandidateEvaluation] = []
        for lot in lots:
            lot_state = await self._twin.get_parking_state(session, lot.parking_lot_id)

            if gate_state.status != "open":
                candidates.append(CandidateEvaluation(lot.parking_lot_id, False, f"gate status is {gate_state.status!r}"))
                continue
            if lot_state is None or lot_state.status != "open":
                status = lot_state.status if lot_state is not None else "unknown"
                candidates.append(CandidateEvaluation(lot.parking_lot_id, False, f"lot status is {status!r}"))
                continue
            if lot_state.occupied is not None and (lot_state.usable_capacity - lot_state.occupied) <= 0:
                candidates.append(CandidateEvaluation(lot.parking_lot_id, False, "lot is full"))
                continue

            try:
                route = await self._navigation.find_route(session, campus_id, gate_id, lot.parking_lot_id, DRIVE)
            except NoFeasibleRouteError:
                candidates.append(
                    CandidateEvaluation(lot.parking_lot_id, False, "no route from gate to lot (blocked road)")
                )
                continue

            candidates.append(
                CandidateEvaluation(
                    lot.parking_lot_id, True, None,
                    travel_time_s=route.travel_time_s, travel_distance_m=route.distance_m,
                )
            )
        return candidates

    async def _predicted_occupancy_pct(
        self, session: AsyncSession, campus_id: str, lot_id: str
    ) -> tuple[float | None, str]:
        prediction = await self._prediction.predict(session, campus_id, lot_id, PREDICTION_HORIZON_MINUTES)
        if prediction.point_estimate is not None and prediction.confidence not in (DATA_STALE, INTELLIGENCE_UNAVAILABLE):
            lot_state = await self._twin.get_parking_state(session, lot_id)
            if lot_state is not None and lot_state.usable_capacity > 0:
                return 100.0 * prediction.point_estimate / lot_state.usable_capacity, "model"

        fallback = await self._historical_average_fallback(session, campus_id, lot_id)
        if fallback is not None:
            return fallback, "historical_average_fallback"

        lot_state = await self._twin.get_parking_state(session, lot_id)
        if lot_state is not None and lot_state.occupied is not None and lot_state.usable_capacity > 0:
            return 100.0 * lot_state.occupied / lot_state.usable_capacity, "current_state_fallback"
        return None, "unavailable"

    async def _historical_average_fallback(
        self, session: AsyncSession, campus_id: str, lot_id: str
    ) -> float | None:
        """A live mean of this lot's own recent real observations -- not
        Module 9's trained pipeline (that may be exactly what's
        unavailable), just enough of a historical signal to keep the
        optimizer scoring instead of failing outright."""

        result = await session.execute(
            select(Observation.occupied_spaces)
            .where(
                Observation.campus_id == campus_id,
                Observation.parking_lot_id == lot_id,
                Observation.occupied_spaces.is_not(None),
            )
            .order_by(Observation.timestamp.desc())
            .limit(50)
        )
        values = [v for (v,) in result.all()]
        if not values:
            return None
        lot_state = await self._twin.get_parking_state(session, lot_id)
        if lot_state is None or lot_state.usable_capacity <= 0:
            return None
        return 100.0 * (sum(values) / len(values)) / lot_state.usable_capacity

    async def _score_candidates(
        self,
        session: AsyncSession,
        campus_id: str,
        gate_id: str,
        feasible: list[CandidateEvaluation],
        weights: dict[str, float],
        started: float,
    ) -> list[CandidateEvaluation] | None:
        predicted_pcts: dict[str, float] = {}
        for candidate in feasible:
            if time.monotonic() - started > TIME_LIMIT_SECONDS:
                return None
            pct, source = await self._predicted_occupancy_pct(session, campus_id, candidate.lot_id)
            candidate.predicted_occupancy_pct = pct
            candidate.prediction_source = source
            if pct is not None:
                predicted_pcts[candidate.lot_id] = pct

        avg_predicted_pct = sum(predicted_pcts.values()) / len(predicted_pcts) if predicted_pcts else 0.0

        gate_wait_raw = 0.0
        if feasible:
            gate_state = await self._twin.get_gate_state(session, gate_id)
            if gate_state is not None and gate_state.queue is not None:
                gate_wait_raw = (
                    float(gate_state.queue) / gate_state.throughput * 60.0
                    if gate_state.throughput
                    else float(gate_state.queue)
                )

        raw_terms: dict[str, ObjectiveTerms] = {}
        for candidate in feasible:
            if time.monotonic() - started > TIME_LIMIT_SECONDS:
                return None

            risk = await self._risk.assess(session, campus_id, candidate.lot_id)
            queue_cost_raw = risk.overflow_risk.score if risk.overflow_risk.available else (
                (candidate.predicted_occupancy_pct or 0.0) / 100.0
            )
            search_travel_raw = candidate.travel_time_s or 0.0
            pct = candidate.predicted_occupancy_pct if candidate.predicted_occupancy_pct is not None else avg_predicted_pct
            utilization_imbalance_raw = abs(pct - avg_predicted_pct) / 100.0
            overflow_penalty_raw = max(0.0, pct - 100.0) / 100.0

            raw_terms[candidate.lot_id] = ObjectiveTerms(
                waiting_time_raw=gate_wait_raw,
                queue_cost_raw=queue_cost_raw,
                search_travel_raw=search_travel_raw,
                utilization_imbalance_raw=utilization_imbalance_raw,
                overflow_penalty_raw=overflow_penalty_raw,
            )

        def _max_or_one(values: list[float]) -> float:
            m = max(values) if values else 0.0
            return m if m > 0 else 1.0

        max_wait = _max_or_one([t.waiting_time_raw for t in raw_terms.values()])
        max_queue = _max_or_one([t.queue_cost_raw for t in raw_terms.values()])
        max_travel = _max_or_one([t.search_travel_raw for t in raw_terms.values()])
        max_imbalance = _max_or_one([t.utilization_imbalance_raw for t in raw_terms.values()])
        max_overflow = _max_or_one([t.overflow_penalty_raw for t in raw_terms.values()])

        for candidate in feasible:
            t = raw_terms[candidate.lot_id]
            t.waiting_time_norm = t.waiting_time_raw / max_wait
            t.queue_cost_norm = t.queue_cost_raw / max_queue
            t.search_travel_norm = t.search_travel_raw / max_travel
            t.utilization_imbalance_norm = t.utilization_imbalance_raw / max_imbalance
            t.overflow_penalty_norm = t.overflow_penalty_raw / max_overflow
            candidate.terms = t
            candidate.objective_j = (
                weights["w1"] * t.waiting_time_norm
                + weights["w2"] * t.queue_cost_norm
                + weights["w3"] * t.search_travel_norm
                + weights["w4"] * t.utilization_imbalance_norm
                + weights["w5"] * t.overflow_penalty_norm
            )

        return feasible
