"""Module 7 — vehicle & parking discrete-time simulation.

Explicitly NOT the optimizer (Module 8): the only allocation strategy
shipped here (NearestAvailableLotStrategy, app.services.allocation) is a
placeholder good enough to make the engine runnable and testable. The
engine itself is strategy-agnostic — Module 8 plugs in real strategies
against the same AllocationStrategy interface.

Every value this module produces is provenance SYNTHETIC: scenario
demand, arrival rates, and parked-duration sampling are all simulator
inputs/assumptions, never measured facts.

A run writes its lot-occupancy changes into Module 3's Digital Twin
(source="simulation", provenance="SYNTHETIC") as they happen, per the
spec. Known limitation this creates: the twin holds one current state
per campus_id, not one per simulation run, so running a simulation
against a campus that is simultaneously receiving real Module 4
ingestion will visibly (if distinguishably, via source/provenance)
overwrite that campus's live occupancy with simulated numbers for the
duration of the run. Run simulations against a non-live campus_id
(e.g. "sample") until a later module adds run-scoped twin isolation.
"""

import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from random import Random

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.simulation import SimulationRun
from app.repositories.campus_config import CampusConfigRepository
from app.scenario_loader.schema import ScenarioConfig
from app.scenario_loader.validators import validate_scenario
from app.services.allocation import (
    AllocationContext,
    AllocationStrategy,
    LotCandidate,
    NearestAvailableLotStrategy,
)
from app.services.campus_config import CampusNotFoundError
from app.services.digital_twin import CapacityExceededError, DigitalTwinService, EntityNotFoundError
from app.services.navigation import DRIVE, NavigationService, NoFeasibleRouteError

logger = logging.getLogger(__name__)

VEHICLE_STATES = ("approaching", "searching", "assigned", "parked", "leaving", "completed")

MIN_PARK_MINUTES = 30
MAX_PARK_MINUTES = 240


class ScenarioValidationFailedError(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _poisson(rng: Random, lam: float) -> int:
    """Knuth's algorithm — deterministic given rng, no numpy dependency."""
    if lam <= 0:
        return 0
    limit = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= limit:
            return k - 1


@dataclass
class _Vehicle:
    vehicle_id: str
    gate_id: str
    arrival_minute: int
    state: str = "approaching"
    queue_exit_minute: int | None = None
    assigned_minute: int | None = None
    assigned_lot_id: str | None = None
    parked_minute: int | None = None
    leave_minute: int | None = None
    departed_minute: int | None = None
    travel_time_s: float = 0.0
    travel_distance_m: float = 0.0
    outcome: str | None = None  # "parked" | "overflow"


@dataclass
class _LotState:
    lot_id: str
    total_capacity: int
    usable_capacity: int
    reserved_or_occupied: int = 0

    @property
    def available(self) -> int:
        return self.usable_capacity - self.reserved_or_occupied


@dataclass
class SimulationResult:
    run_id: str
    campus_id: str
    scenario_id: str
    seed: int
    duration_minutes: int
    started_at: datetime
    finished_at: datetime
    metrics: dict = field(default_factory=dict)
    run_log: list[dict] = field(default_factory=list)


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


class SimulationEngine:
    def __init__(
        self,
        config_repository: CampusConfigRepository | None = None,
        navigation_service: NavigationService | None = None,
        twin_service: DigitalTwinService | None = None,
    ) -> None:
        self._config = config_repository or CampusConfigRepository()
        self._navigation = navigation_service or NavigationService()
        self._twin = twin_service or DigitalTwinService()

    async def validate(self, session: AsyncSession, scenario: ScenarioConfig) -> None:
        campus = await self._config.get_campus(session, scenario.campus_id)
        if campus is None:
            raise CampusNotFoundError(scenario.campus_id)

        gate_ids = {g.gate_id for g in await self._config.list_gates(session, scenario.campus_id)}
        lot_ids = {p.parking_lot_id for p in await self._config.list_parking_lots(session, scenario.campus_id)}
        road_ids = {r.road_id for r in await self._config.list_roads(session, scenario.campus_id)}

        errors = validate_scenario(scenario, gate_ids, lot_ids, road_ids)
        if errors:
            raise ScenarioValidationFailedError(errors)

    async def _travel_table(
        self, session: AsyncSession, campus_id: str, gate_ids: list[str], lot_ids: list[str]
    ) -> dict[str, dict[str, tuple[float, float]]]:
        """gate_id -> lot_id -> (travel_time_s, distance_m), from Module 6's
        real routing — never guessed."""

        table: dict[str, dict[str, tuple[float, float]]] = {gate_id: {} for gate_id in gate_ids}
        for gate_id in gate_ids:
            for lot_id in lot_ids:
                try:
                    route = await self._navigation.find_route(session, campus_id, gate_id, lot_id, DRIVE)
                except NoFeasibleRouteError:
                    continue
                table[gate_id][lot_id] = (route.travel_time_s, route.distance_m)
        return table

    async def run(
        self,
        session: AsyncSession,
        scenario: ScenarioConfig,
        seed: int | None = None,
        strategy: AllocationStrategy | None = None,
    ) -> SimulationResult:
        await self.validate(session, scenario)

        effective_seed = scenario.seed if seed is None else seed
        rng = Random(effective_seed)
        strategy = strategy or NearestAvailableLotStrategy()
        # Ensures every lot has a twin row to update; never touches an
        # existing real observation (see DigitalTwinService.init_campus).
        await self._twin.init_campus(session, scenario.campus_id)
        sim_clock_start = datetime.now(timezone.utc)

        async def record_twin_update(lot_state: "_LotState", minute: int) -> None:
            try:
                await self._twin.update_parking(
                    session,
                    scenario.campus_id,
                    lot_state.lot_id,
                    occupied=lot_state.reserved_or_occupied,
                    source="simulation",
                    provenance="SYNTHETIC",
                    observation_timestamp=sim_clock_start + timedelta(minutes=minute),
                )
            except (EntityNotFoundError, CapacityExceededError) as exc:
                # A scenario's capacity_override can raise the lot above (or
                # keep it below) the twin's config-seeded total_capacity;
                # either way the simulation's own bookkeeping (lot_states,
                # the hard capacity-never-exceeded guarantee) is authoritative
                # for this run — a twin sync miss doesn't invalidate it.
                logger.warning(
                    "simulation twin sync skipped",
                    extra={"campus_id": scenario.campus_id, "lot_id": lot_state.lot_id, "reason": str(exc)},
                )

        gates = sorted(await self._config.list_gates(session, scenario.campus_id), key=lambda g: g.gate_id)
        lots = sorted(await self._config.list_parking_lots(session, scenario.campus_id), key=lambda p: p.parking_lot_id)
        gate_ids = [g.gate_id for g in gates]
        lot_ids = [lot.parking_lot_id for lot in lots]

        travel_table = await self._travel_table(session, scenario.campus_id, gate_ids, lot_ids)

        capacity_overrides = {o.parking_lot_id: o for o in scenario.capacity_overrides}
        lot_states: dict[str, _LotState] = {}
        for lot in lots:
            override = capacity_overrides.get(lot.parking_lot_id)
            total = override.total_capacity if override else lot.total_capacity
            usable = override.usable_capacity if override else lot.usable_capacity
            lot_states[lot.parking_lot_id] = _LotState(lot.parking_lot_id, total, usable)

        gate_closed_windows = [
            o for o in scenario.availability_overrides if o.entity_type == "gate" and o.status == "closed"
        ]
        lot_closed_windows = [
            o for o in scenario.availability_overrides if o.entity_type == "parking_lot" and o.status == "closed"
        ]

        def is_closed(windows: list, entity_id: str, minute: int) -> bool:
            return any(w.entity_id == entity_id and w.start_minute <= minute < w.end_minute for w in windows)

        def active_demand_multiplier(minute: int) -> float:
            multiplier = 1.0
            for event in scenario.event_conditions:
                if event.start_minute <= minute < event.end_minute:
                    multiplier *= event.demand_multiplier
            return multiplier

        gate_queues: dict[str, list[_Vehicle]] = {gate_id: [] for gate_id in gate_ids}
        arrivals_at_lot: dict[int, list[_Vehicle]] = {}
        departures: dict[int, list[_Vehicle]] = {}
        vehicles: list[_Vehicle] = []
        overflow_count = 0
        run_log: list[dict] = []
        vehicle_seq = 0

        for minute in range(scenario.duration_minutes):
            demand_multiplier = active_demand_multiplier(minute)

            # 1. Arrivals.
            for entry in scenario.arrival_rate_profile:
                if not (entry.start_minute <= minute < entry.end_minute):
                    continue
                if is_closed(gate_closed_windows, entry.gate_id, minute):
                    continue
                lam = entry.vehicles_per_minute * demand_multiplier
                count = _poisson(rng, lam)
                for _ in range(count):
                    vehicle_seq += 1
                    vehicle = _Vehicle(
                        vehicle_id=f"veh-{vehicle_seq}", gate_id=entry.gate_id, arrival_minute=minute
                    )
                    vehicles.append(vehicle)
                    gate_queues[entry.gate_id].append(vehicle)

            # 2. Gate throughput -> searching -> allocate.
            for gate in gates:
                if is_closed(gate_closed_windows, gate.gate_id, minute):
                    continue
                throughput = max(1, gate.capacity)
                queue = gate_queues[gate.gate_id]
                dequeued, gate_queues[gate.gate_id] = queue[:throughput], queue[throughput:]
                for vehicle in dequeued:
                    vehicle.state = "searching"
                    vehicle.queue_exit_minute = minute

                    candidates = []
                    for lot_id, (travel_time_s, _distance_m) in sorted(travel_table.get(gate.gate_id, {}).items()):
                        if is_closed(lot_closed_windows, lot_id, minute):
                            continue
                        lot_state = lot_states[lot_id]
                        jitter = rng.gauss(0, scenario.prediction_error_level * max(lot_state.usable_capacity, 1))
                        apparent = lot_state.available + jitter
                        candidates.append(LotCandidate(lot_id, travel_time_s, apparent))

                    chosen = strategy.choose(AllocationContext(minute, gate.gate_id, candidates, rng))

                    if chosen is None or lot_states[chosen].available <= 0:
                        vehicle.state = "completed"
                        vehicle.outcome = "overflow"
                        overflow_count += 1
                        continue

                    lot_state = lot_states[chosen]
                    lot_state.reserved_or_occupied += 1
                    vehicle.state = "assigned"
                    vehicle.assigned_minute = minute
                    vehicle.assigned_lot_id = chosen
                    vehicle.travel_time_s, vehicle.travel_distance_m = travel_table[gate.gate_id][chosen]
                    await record_twin_update(lot_state, minute)
                    arrival_at_lot = minute + max(1, round(vehicle.travel_time_s / 60))
                    arrivals_at_lot.setdefault(arrival_at_lot, []).append(vehicle)

            # 3. Arrivals at lot -> parked, schedule departure.
            for vehicle in arrivals_at_lot.pop(minute, []):
                vehicle.state = "parked"
                vehicle.parked_minute = minute
                vehicle.outcome = "parked"
                park_duration = rng.randint(MIN_PARK_MINUTES, MAX_PARK_MINUTES)
                vehicle.leave_minute = minute + park_duration
                departures.setdefault(vehicle.leave_minute, []).append(vehicle)

            # 4. Departures.
            for vehicle in departures.pop(minute, []):
                vehicle.state = "leaving"
                lot_state = lot_states[vehicle.assigned_lot_id]
                lot_state.reserved_or_occupied -= 1
                vehicle.state = "completed"
                vehicle.departed_minute = minute
                await record_twin_update(lot_state, minute)

            run_log.append(
                {
                    "minute": minute,
                    "gate_queue_lengths": {gate_id: len(gate_queues[gate_id]) for gate_id in gate_ids},
                    "lot_occupied": {lot_id: lot_states[lot_id].reserved_or_occupied for lot_id in lot_ids},
                }
            )

        metrics = self._compute_metrics(vehicles, lot_states, lot_ids, run_log, overflow_count)

        started_at = datetime.now(timezone.utc)
        return SimulationResult(
            run_id=f"sim_{uuid.uuid4().hex}",
            campus_id=scenario.campus_id,
            scenario_id=scenario.scenario_id,
            seed=effective_seed,
            duration_minutes=scenario.duration_minutes,
            started_at=started_at,
            finished_at=started_at,
            metrics=metrics,
            run_log=run_log,
        )

    @staticmethod
    def _compute_metrics(
        vehicles: list[_Vehicle],
        lot_states: dict[str, _LotState],
        lot_ids: list[str],
        run_log: list[dict],
        overflow_count: int,
    ) -> dict:
        wait_times = [v.queue_exit_minute - v.arrival_minute for v in vehicles if v.queue_exit_minute is not None]
        search_times = [
            v.assigned_minute - v.queue_exit_minute
            for v in vehicles
            if v.assigned_minute is not None and v.queue_exit_minute is not None
        ]
        travel_times_s = [v.travel_time_s for v in vehicles if v.outcome == "parked"]
        travel_distances_m = [v.travel_distance_m for v in vehicles if v.outcome == "parked"]

        utilization_by_lot = {}
        for lot_id in lot_ids:
            samples = [entry["lot_occupied"][lot_id] for entry in run_log]
            capacity = lot_states[lot_id].usable_capacity
            utilization_by_lot[lot_id] = {
                "peak_occupied": max(samples) if samples else 0,
                "avg_occupancy_pct": round(100 * sum(samples) / (len(samples) * capacity), 1)
                if samples and capacity > 0
                else None,
            }

        max_queue_by_gate: dict[str, int] = {}
        for entry in run_log:
            for gate_id, length in entry["gate_queue_lengths"].items():
                max_queue_by_gate[gate_id] = max(max_queue_by_gate.get(gate_id, 0), length)

        return {
            "vehicles_total": len(vehicles),
            "vehicles_parked": sum(1 for v in vehicles if v.outcome == "parked"),
            "overflow_count": overflow_count,
            "gate_wait_time_minutes": {
                "avg": round(sum(wait_times) / len(wait_times), 2) if wait_times else None,
                "p95": _percentile([float(w) for w in wait_times], 95),
                "max": max(wait_times) if wait_times else None,
            },
            "search_time_minutes": {
                "avg": round(sum(search_times) / len(search_times), 2) if search_times else None,
                "p95": _percentile([float(s) for s in search_times], 95),
                "max": max(search_times) if search_times else None,
            },
            "travel_time_seconds": {
                "avg": round(sum(travel_times_s) / len(travel_times_s), 1) if travel_times_s else None,
                "max": max(travel_times_s) if travel_times_s else None,
            },
            "travel_distance_meters": {
                "avg": round(sum(travel_distances_m) / len(travel_distances_m), 1) if travel_distances_m else None,
                "max": max(travel_distances_m) if travel_distances_m else None,
            },
            "max_gate_queue_length": max_queue_by_gate,
            "utilization_by_lot": utilization_by_lot,
        }

    async def run_and_store(
        self,
        session: AsyncSession,
        scenario: ScenarioConfig,
        seed: int | None = None,
        strategy: AllocationStrategy | None = None,
    ) -> SimulationRun:
        result = await self.run(session, scenario, seed, strategy)
        run = SimulationRun(
            run_id=result.run_id,
            campus_id=result.campus_id,
            scenario_id=result.scenario_id,
            seed=result.seed,
            started_at=result.started_at,
            finished_at=result.finished_at,
            duration_minutes=result.duration_minutes,
            metrics=result.metrics,
            run_log=result.run_log,
        )
        session.add(run)
        await session.commit()
        return run
