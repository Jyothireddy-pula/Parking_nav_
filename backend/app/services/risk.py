"""Module 10 — risk engine. Converts Module 3's current state and Module
9's predictions into danger levels. Never decides what to do about them
(no allocation, no routing, no notifications) -- that is left to a later
module (optimization reads risk, it doesn't compute it).

Every sub-risk is scored as `raw_value / threshold` (a ratio) and banded
into LOW/MEDIUM/HIGH/CRITICAL via one shared, documented policy
(`_band_ratio`) -- not independently tuned per dimension. All thresholds
below are explicit starting policy, same shape as Module 5's CV promotion
threshold and Module 9's confidence bands: not validated against real
VIT-AP outcomes, because none exist yet.

Deliberate simplification, documented rather than silently assumed: gate
queue risk and road congestion risk are campus-wide (the single worst gate
queue / worst road load on the whole campus), not specific to whichever
gate/road actually serves this lot. Module 1's config never associates a
specific gate with a specific lot, and no module has ever written real
road telemetry (`DigitalTwinService.update_road` has zero callers in this
codebase today) -- so road congestion risk is UNKNOWN in practice until a
future module starts collecting it. That absence is reported explicitly,
never guessed at.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.campus_config import CampusConfigRepository
from app.repositories.twin import TwinRepository
from app.services.campus_config import CampusNotFoundError
from app.services.prediction import (
    DATA_STALE,
    INTELLIGENCE_UNAVAILABLE,
    PredictionResult,
    PredictionService,
)

LOW, MEDIUM, HIGH, CRITICAL, UNKNOWN = "LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"

# ratio = raw_value / threshold. Shared banding policy across every
# dimension -- documented starting policy, not yet validated.
MEDIUM_AT_RATIO = 0.8
HIGH_AT_RATIO = 1.0
CRITICAL_AT_RATIO = 1.15

OVERFLOW_THRESHOLD_PCT = 90.0  # predicted upper-bound occupancy, e.g. "90%" from the spec
GATE_QUEUE_THRESHOLD = 15.0  # vehicles queued, campus-wide worst gate
ROAD_LOAD_THRESHOLD = 0.8  # RoadState.load, campus-wide worst road -- never yet measured, see module docstring
SEARCH_RISK_THRESHOLD_PCT = 70.0  # scarcity-weighted occupancy score, see _search_risk

PREDICTION_HORIZON_MINUTES = 15  # the horizon the proactive trigger and overflow risk both use

# combined network risk weights -- equal-ish, overflow weighted slightly
# higher since it is the most direct predictive signal of the four.
# Renormalized across whichever dimensions are actually available.
NETWORK_RISK_WEIGHTS = {"overflow": 0.4, "gate_queue": 0.2, "road_congestion": 0.2, "search": 0.2}


def _band_ratio(ratio: float) -> str:
    if ratio >= CRITICAL_AT_RATIO:
        return CRITICAL
    if ratio >= HIGH_AT_RATIO:
        return HIGH
    if ratio >= MEDIUM_AT_RATIO:
        return MEDIUM
    return LOW


@dataclass
class RiskComponent:
    available: bool
    level: str
    raw_value: float | None
    threshold: float | None
    score: float | None  # raw_value / threshold, the same ratio _band_ratio used
    reason: str | None = None


@dataclass
class ProactiveTrigger:
    fired: bool
    reason: str
    current_occupancy_pct: float | None
    predicted_upper_bound_pct: float | None
    threshold_pct: float = OVERFLOW_THRESHOLD_PCT


@dataclass
class RiskAssessment:
    campus_id: str
    lot_id: str
    lot_status: str
    assessed_at: datetime
    overflow_risk: RiskComponent
    gate_queue_risk: RiskComponent
    road_congestion_risk: RiskComponent
    search_risk: RiskComponent
    combined_network_risk: RiskComponent
    proactive_trigger: ProactiveTrigger
    prediction: PredictionResult | None
    excluded_from_combined: list[str] = field(default_factory=list)


class LotNotFoundError(Exception):
    def __init__(self, campus_id: str, lot_id: str) -> None:
        self.campus_id = campus_id
        self.lot_id = lot_id
        super().__init__(f"parking_lot {lot_id!r} not found on campus {campus_id!r}")


class RiskEngine:
    def __init__(
        self,
        prediction_service: PredictionService,
        config_repository: CampusConfigRepository | None = None,
        twin_repository: TwinRepository | None = None,
    ) -> None:
        self._prediction = prediction_service
        self._config = config_repository or CampusConfigRepository()
        self._twin = twin_repository or TwinRepository()

    async def assess(self, session: AsyncSession, campus_id: str, lot_id: str) -> RiskAssessment:
        campus = await self._config.get_campus(session, campus_id)
        if campus is None:
            raise CampusNotFoundError(campus_id)

        lot_state = await self._twin.get_parking_state(session, lot_id)
        if lot_state is None or lot_state.campus_id != campus_id:
            raise LotNotFoundError(campus_id, lot_id)

        now = datetime.now(timezone.utc)
        prediction: PredictionResult | None = None
        overflow: RiskComponent
        proactive: ProactiveTrigger

        if lot_state.status != "open":
            overflow = RiskComponent(
                available=True, level=LOW, raw_value=None, threshold=OVERFLOW_THRESHOLD_PCT, score=None,
                reason=f"lot status is {lot_state.status!r}: not accepting new vehicles, no overflow risk",
            )
            proactive = ProactiveTrigger(
                fired=False,
                reason=f"lot status is {lot_state.status!r}: proactive trigger does not apply",
                current_occupancy_pct=_occupancy_pct(lot_state),
                predicted_upper_bound_pct=None,
            )
        else:
            prediction = await self._prediction.predict(session, campus_id, lot_id, PREDICTION_HORIZON_MINUTES)
            overflow, proactive = self._overflow_and_trigger(lot_state, prediction)

        gate_queue = await self._gate_queue_risk(session, campus_id)
        road_congestion = await self._road_congestion_risk(session, campus_id)
        search = await self._search_risk(session, campus_id, lot_id, lot_state)
        combined, excluded = self._combined_network_risk(overflow, gate_queue, road_congestion, search)

        return RiskAssessment(
            campus_id=campus_id,
            lot_id=lot_id,
            lot_status=lot_state.status,
            assessed_at=now,
            overflow_risk=overflow,
            gate_queue_risk=gate_queue,
            road_congestion_risk=road_congestion,
            search_risk=search,
            combined_network_risk=combined,
            proactive_trigger=proactive,
            prediction=prediction,
            excluded_from_combined=excluded,
        )

    async def is_proactive_trigger(self, session: AsyncSession, campus_id: str, lot_id: str) -> ProactiveTrigger:
        """Fires the instant the PREDICTED occupancy crosses
        OVERFLOW_THRESHOLD_PCT, even while current occupancy hasn't --
        e.g. current 72%, 15-min prediction 94%+/-3% (upper bound 97%),
        threshold 90% -> fires now."""

        assessment = await self.assess(session, campus_id, lot_id)
        return assessment.proactive_trigger

    @staticmethod
    def _overflow_and_trigger(lot_state, prediction: PredictionResult) -> tuple[RiskComponent, ProactiveTrigger]:
        current_pct = _occupancy_pct(lot_state)

        if prediction.confidence in (DATA_STALE, INTELLIGENCE_UNAVAILABLE) or prediction.upper_bound is None:
            overflow = RiskComponent(
                available=False, level=UNKNOWN, raw_value=None, threshold=OVERFLOW_THRESHOLD_PCT, score=None,
                reason=f"prediction confidence is {prediction.confidence}: overflow risk cannot be scored, "
                "not defaulted",
            )
            proactive = ProactiveTrigger(
                fired=False,
                reason=f"prediction confidence is {prediction.confidence}: cannot evaluate the proactive trigger",
                current_occupancy_pct=current_pct,
                predicted_upper_bound_pct=None,
            )
            return overflow, proactive

        capacity = lot_state.usable_capacity
        upper_pct = 100.0 * prediction.upper_bound / capacity if capacity > 0 else None
        if upper_pct is None:
            overflow = RiskComponent(
                available=False, level=UNKNOWN, raw_value=None, threshold=OVERFLOW_THRESHOLD_PCT, score=None,
                reason="lot has zero usable_capacity: overflow risk is undefined",
            )
            proactive = ProactiveTrigger(
                fired=False, reason="lot has zero usable_capacity: cannot evaluate the proactive trigger",
                current_occupancy_pct=current_pct, predicted_upper_bound_pct=None,
            )
            return overflow, proactive

        ratio = upper_pct / OVERFLOW_THRESHOLD_PCT
        overflow = RiskComponent(
            available=True, level=_band_ratio(ratio), raw_value=upper_pct, threshold=OVERFLOW_THRESHOLD_PCT,
            score=ratio,
        )
        fired = upper_pct >= OVERFLOW_THRESHOLD_PCT
        proactive = ProactiveTrigger(
            fired=fired,
            reason=(
                f"predicted upper bound {upper_pct:.1f}% >= threshold {OVERFLOW_THRESHOLD_PCT:.1f}%"
                if fired
                else f"predicted upper bound {upper_pct:.1f}% below threshold {OVERFLOW_THRESHOLD_PCT:.1f}%"
            ),
            current_occupancy_pct=current_pct,
            predicted_upper_bound_pct=upper_pct,
        )
        return overflow, proactive

    async def _gate_queue_risk(self, session: AsyncSession, campus_id: str) -> RiskComponent:
        gates = await self._twin.list_gate_states(session, campus_id)
        queues = [g.queue for g in gates if g.queue is not None]
        if not queues:
            return RiskComponent(
                available=False, level=UNKNOWN, raw_value=None, threshold=GATE_QUEUE_THRESHOLD, score=None,
                reason="no gate queue observations available on this campus",
            )
        worst = float(max(queues))
        ratio = worst / GATE_QUEUE_THRESHOLD
        return RiskComponent(available=True, level=_band_ratio(ratio), raw_value=worst,
                              threshold=GATE_QUEUE_THRESHOLD, score=ratio)

    async def _road_congestion_risk(self, session: AsyncSession, campus_id: str) -> RiskComponent:
        roads = await self._twin.list_road_states(session, campus_id)
        loads = [r.load for r in roads if r.load is not None]
        if not loads:
            return RiskComponent(
                available=False, level=UNKNOWN, raw_value=None, threshold=ROAD_LOAD_THRESHOLD, score=None,
                reason="no road load observations available on this campus (no module populates this yet)",
            )
        worst = float(max(loads))
        ratio = worst / ROAD_LOAD_THRESHOLD
        return RiskComponent(available=True, level=_band_ratio(ratio), raw_value=worst,
                              threshold=ROAD_LOAD_THRESHOLD, score=ratio)

    async def _search_risk(self, session: AsyncSession, campus_id: str, lot_id: str, lot_state) -> RiskComponent:
        """How hard it is, right now, to actually find a space: this lot's
        current occupancy, dampened by how many other open lots on campus
        currently have room. Uses CURRENT state only (not the prediction),
        so it stays available even when Module 9's prediction doesn't."""

        current_pct = _occupancy_pct(lot_state)
        if current_pct is None:
            return RiskComponent(
                available=False, level=UNKNOWN, raw_value=None, threshold=SEARCH_RISK_THRESHOLD_PCT, score=None,
                reason="no current occupancy observation for this lot",
            )

        all_lots = await self._twin.list_parking_states(session, campus_id)
        alternatives_with_room = sum(
            1
            for other in all_lots
            if other.parking_lot_id != lot_id
            and other.status == "open"
            and other.occupied is not None
            and (other.usable_capacity - other.occupied) > 0
        )
        scarcity_factor = 1.0 / (1.0 + alternatives_with_room)
        search_score = current_pct * scarcity_factor
        ratio = search_score / SEARCH_RISK_THRESHOLD_PCT
        return RiskComponent(available=True, level=_band_ratio(ratio), raw_value=search_score,
                              threshold=SEARCH_RISK_THRESHOLD_PCT, score=ratio)

    @staticmethod
    def _combined_network_risk(
        overflow: RiskComponent, gate_queue: RiskComponent, road_congestion: RiskComponent, search: RiskComponent
    ) -> tuple[RiskComponent, list[str]]:
        components = {"overflow": overflow, "gate_queue": gate_queue, "road_congestion": road_congestion,
                      "search": search}
        available = {name: c for name, c in components.items() if c.available and c.score is not None}
        excluded = [name for name in components if name not in available]

        if not available:
            return (
                RiskComponent(
                    available=False, level=UNKNOWN, raw_value=None, threshold=None, score=None,
                    reason="no risk dimension could be scored: " + ", ".join(f"{c.reason}" for c in components.values()),
                ),
                excluded,
            )

        weight_sum = sum(NETWORK_RISK_WEIGHTS[name] for name in available)
        combined_ratio = sum(NETWORK_RISK_WEIGHTS[name] * c.score for name, c in available.items()) / weight_sum
        reason = f"excluded: {', '.join(excluded)}" if excluded else None
        return (
            RiskComponent(available=True, level=_band_ratio(combined_ratio), raw_value=combined_ratio,
                           threshold=1.0, score=combined_ratio, reason=reason),
            excluded,
        )


def _occupancy_pct(lot_state) -> float | None:
    if lot_state.occupied is None or lot_state.usable_capacity <= 0:
        return None
    return 100.0 * lot_state.occupied / lot_state.usable_capacity
