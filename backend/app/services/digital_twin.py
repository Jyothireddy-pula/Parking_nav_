import logging
from datetime import datetime, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.twin import (
    OBSERVATION_SOURCES,
    PROVENANCE_LABELS,
    VEHICLE_STATES,
    CampusState,
    GateState,
    ParkingState,
    RoadState,
    TwinSnapshot,
    VehicleState,
)
from app.repositories.campus_config import CampusConfigRepository
from app.repositories.twin import TwinRepository
from app.services.campus_config import CampusNotFoundError
from app.services.freshness import compute_freshness

logger = logging.getLogger(__name__)


class EntityNotFoundError(Exception):
    def __init__(self, entity_type: str, entity_id: str) -> None:
        self.entity_type = entity_type
        self.entity_id = entity_id
        super().__init__(f"{entity_type} {entity_id!r} not found in the digital twin")


class InvalidObservationError(Exception):
    pass


class CapacityExceededError(Exception):
    def __init__(self, parking_lot_id: str, occupied: int, ceiling: int) -> None:
        self.parking_lot_id = parking_lot_id
        self.occupied = occupied
        self.ceiling = ceiling
        super().__init__(
            f"parking_lot {parking_lot_id!r}: occupied={occupied} exceeds capacity ceiling={ceiling}"
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_source(source: str) -> None:
    if source not in OBSERVATION_SOURCES:
        raise InvalidObservationError(f"source must be one of {OBSERVATION_SOURCES}, got {source!r}")


def _validate_provenance(provenance: str) -> None:
    if provenance not in PROVENANCE_LABELS:
        raise InvalidObservationError(f"provenance must be one of {PROVENANCE_LABELS}, got {provenance!r}")


class DigitalTwinService:
    def __init__(
        self,
        twin_repository: TwinRepository | None = None,
        config_repository: CampusConfigRepository | None = None,
    ) -> None:
        self._twin = twin_repository or TwinRepository()
        self._config = config_repository or CampusConfigRepository()

    async def _require_campus(self, session: AsyncSession, campus_id: str) -> None:
        campus = await self._config.get_campus(session, campus_id)
        if campus is None:
            raise CampusNotFoundError(campus_id)

    # -- init ---------------------------------------------------------

    async def init_campus(self, session: AsyncSession, campus_id: str) -> CampusState:
        """Seed (or refresh) the twin's structural rows from Module 1's
        config. Existing observations (occupied, queue, timestamps, ...) are
        preserved for entities that already have a twin row; only the
        config-derived fields (capacity breakdown, structural status) are
        refreshed. New entities in the config get a fresh, unobserved row."""

        campus = await self._config.get_campus(session, campus_id)
        if campus is None:
            raise CampusNotFoundError(campus_id)

        campus_state = await session.get(CampusState, campus_id)
        if campus_state is None:
            campus_state = CampusState(
                campus_id=campus_id, active_scenario="normal", config_version=campus.active_configuration_version
            )
        else:
            campus_state.config_version = campus.active_configuration_version
        await session.merge(campus_state)

        for lot in await self._config.list_parking_lots(session, campus_id):
            existing = await session.get(ParkingState, lot.parking_lot_id)
            row = existing or ParkingState(parking_lot_id=lot.parking_lot_id, campus_id=campus_id, status=lot.status)
            row.campus_id = campus_id
            row.total_capacity = lot.total_capacity
            row.usable_capacity = lot.usable_capacity
            row.reserved_capacity = lot.reserved_capacity
            row.restricted_capacity = lot.restricted_capacity
            row.temporarily_unavailable_capacity = lot.temporarily_unavailable_capacity
            if existing is None:
                row.status = lot.status
            await session.merge(row)

        for gate in await self._config.list_gates(session, campus_id):
            existing = await session.get(GateState, gate.gate_id)
            row = existing or GateState(gate_id=gate.gate_id, campus_id=campus_id, status=gate.status)
            row.campus_id = campus_id
            if existing is None:
                row.status = gate.status
            await session.merge(row)

        for road in await self._config.list_roads(session, campus_id):
            existing = await session.get(RoadState, road.road_id)
            row = existing or RoadState(road_id=road.road_id, campus_id=campus_id, status=road.status)
            row.campus_id = campus_id
            if existing is None:
                row.status = road.status
            await session.merge(row)

        await session.commit()
        return await session.get(CampusState, campus_id)

    # -- updates --------------------------------------------------------

    async def update_parking(
        self,
        session: AsyncSession,
        campus_id: str,
        lot_id: str,
        occupied: int,
        source: str,
        provenance: str,
        status: str | None = None,
        predicted_occupancy: float | None = None,
        observation_timestamp: datetime | None = None,
    ) -> ParkingState:
        await self._require_campus(session, campus_id)
        _validate_source(source)
        _validate_provenance(provenance)

        row = await self._twin.get_parking_state(session, lot_id)
        if row is None or row.campus_id != campus_id:
            raise EntityNotFoundError("parking_lot", lot_id)

        if occupied < 0:
            raise InvalidObservationError(f"occupied must be >= 0, got {occupied}")
        if occupied > row.total_capacity:
            logger.warning(
                "rejected over-capacity parking observation",
                extra={"parking_lot_id": lot_id, "occupied": occupied, "total_capacity": row.total_capacity},
            )
            raise CapacityExceededError(lot_id, occupied, row.total_capacity)

        row.occupied = occupied
        if status is not None:
            row.status = status
        if predicted_occupancy is not None:
            row.predicted_occupancy = predicted_occupancy
        row.observation_timestamp = observation_timestamp or _now()
        row.ingestion_timestamp = _now()
        row.source = source
        row.provenance = provenance

        await session.merge(row)
        await session.commit()
        return await self._twin.get_parking_state(session, lot_id)

    async def update_gate(
        self,
        session: AsyncSession,
        campus_id: str,
        gate_id: str,
        queue: int,
        throughput: float,
        source: str,
        provenance: str,
        status: str | None = None,
        observation_timestamp: datetime | None = None,
    ) -> GateState:
        await self._require_campus(session, campus_id)
        _validate_source(source)
        _validate_provenance(provenance)

        row = await self._twin.get_gate_state(session, gate_id)
        if row is None or row.campus_id != campus_id:
            raise EntityNotFoundError("gate", gate_id)
        if queue < 0:
            raise InvalidObservationError(f"queue must be >= 0, got {queue}")

        row.queue = queue
        row.throughput = throughput
        if status is not None:
            row.status = status
        row.observation_timestamp = observation_timestamp or _now()
        row.ingestion_timestamp = _now()
        row.source = source
        row.provenance = provenance

        await session.merge(row)
        await session.commit()
        return await self._twin.get_gate_state(session, gate_id)

    async def update_road(
        self,
        session: AsyncSession,
        campus_id: str,
        road_id: str,
        load: float,
        congestion: str,
        source: str,
        provenance: str,
        status: str | None = None,
        observation_timestamp: datetime | None = None,
    ) -> RoadState:
        await self._require_campus(session, campus_id)
        _validate_source(source)
        _validate_provenance(provenance)

        row = await self._twin.get_road_state(session, road_id)
        if row is None or row.campus_id != campus_id:
            raise EntityNotFoundError("road", road_id)
        if load < 0:
            raise InvalidObservationError(f"load must be >= 0, got {load}")

        row.load = load
        row.congestion = congestion
        if status is not None:
            row.status = status
        row.observation_timestamp = observation_timestamp or _now()
        row.ingestion_timestamp = _now()
        row.source = source
        row.provenance = provenance

        await session.merge(row)
        await session.commit()
        return await self._twin.get_road_state(session, road_id)

    async def update_vehicle(
        self,
        session: AsyncSession,
        campus_id: str,
        vehicle_id: str,
        state: str,
        source: str,
        provenance: str,
        assigned_parking_lot_id: str | None = None,
        observation_timestamp: datetime | None = None,
    ) -> VehicleState:
        await self._require_campus(session, campus_id)
        _validate_source(source)
        _validate_provenance(provenance)
        if state not in VEHICLE_STATES:
            raise InvalidObservationError(f"state must be one of {VEHICLE_STATES}, got {state!r}")

        row = await session.get(VehicleState, vehicle_id) or VehicleState(
            vehicle_id=vehicle_id, campus_id=campus_id, state=state
        )
        row.campus_id = campus_id
        row.state = state
        row.assigned_parking_lot_id = assigned_parking_lot_id
        row.observation_timestamp = observation_timestamp or _now()
        row.ingestion_timestamp = _now()
        row.source = source
        row.provenance = provenance

        await session.merge(row)
        await session.commit()
        return await session.get(VehicleState, vehicle_id)

    # -- reads ------------------------------------------------------------

    @staticmethod
    def _annotate_parking(row: ParkingState, now: datetime) -> dict:
        available = row.usable_capacity - row.occupied if row.occupied is not None else None
        occupancy_pct = (
            round(100.0 * row.occupied / row.usable_capacity, 1)
            if row.occupied is not None and row.usable_capacity > 0
            else None
        )
        return {
            "parking_lot_id": row.parking_lot_id,
            "campus_id": row.campus_id,
            "total_capacity": row.total_capacity,
            "usable_capacity": row.usable_capacity,
            "reserved_capacity": row.reserved_capacity,
            "restricted_capacity": row.restricted_capacity,
            "temporarily_unavailable_capacity": row.temporarily_unavailable_capacity,
            "occupied": row.occupied,
            "available": available,
            "occupancy_pct": occupancy_pct,
            "predicted_occupancy": row.predicted_occupancy,
            "status": row.status,
            "observation_timestamp": row.observation_timestamp,
            "ingestion_timestamp": row.ingestion_timestamp,
            "source": row.source,
            "provenance": row.provenance,
            "freshness": compute_freshness(row.observation_timestamp, "parking", now),
        }

    @staticmethod
    def _annotate_gate(row: GateState, now: datetime) -> dict:
        return {
            "gate_id": row.gate_id,
            "campus_id": row.campus_id,
            "queue": row.queue,
            "throughput": row.throughput,
            "status": row.status,
            "observation_timestamp": row.observation_timestamp,
            "ingestion_timestamp": row.ingestion_timestamp,
            "source": row.source,
            "provenance": row.provenance,
            "freshness": compute_freshness(row.observation_timestamp, "gate", now),
        }

    @staticmethod
    def _annotate_road(row: RoadState, now: datetime) -> dict:
        return {
            "road_id": row.road_id,
            "campus_id": row.campus_id,
            "load": row.load,
            "congestion": row.congestion,
            "status": row.status,
            "observation_timestamp": row.observation_timestamp,
            "ingestion_timestamp": row.ingestion_timestamp,
            "source": row.source,
            "provenance": row.provenance,
            "freshness": compute_freshness(row.observation_timestamp, "road", now),
        }

    @staticmethod
    def _annotate_vehicle(row: VehicleState, now: datetime) -> dict:
        return {
            "vehicle_id": row.vehicle_id,
            "campus_id": row.campus_id,
            "state": row.state,
            "assigned_parking_lot_id": row.assigned_parking_lot_id,
            "observation_timestamp": row.observation_timestamp,
            "ingestion_timestamp": row.ingestion_timestamp,
            "source": row.source,
            "provenance": row.provenance,
            "freshness": compute_freshness(row.observation_timestamp, "vehicle", now),
        }

    async def get_state(self, session: AsyncSession, campus_id: str) -> dict:
        await self._require_campus(session, campus_id)
        now = _now()

        campus_state = await self._twin.get_campus_state(session, campus_id)
        parking = await self._twin.list_parking_states(session, campus_id)
        gates = await self._twin.list_gate_states(session, campus_id)
        roads = await self._twin.list_road_states(session, campus_id)
        vehicles = await self._twin.list_vehicle_states(session, campus_id)

        return {
            "campus_id": campus_id,
            "active_scenario": campus_state.active_scenario if campus_state else None,
            "config_version": campus_state.config_version if campus_state else None,
            "parking": [self._annotate_parking(row, now) for row in parking],
            "gates": [self._annotate_gate(row, now) for row in gates],
            "roads": [self._annotate_road(row, now) for row in roads],
            "vehicles": [self._annotate_vehicle(row, now) for row in vehicles],
            "generated_at": now,
        }

    async def get_parking_state(self, session: AsyncSession, campus_id: str, lot_id: str) -> dict:
        await self._require_campus(session, campus_id)
        row = await self._twin.get_parking_state(session, lot_id)
        if row is None or row.campus_id != campus_id:
            raise EntityNotFoundError("parking_lot", lot_id)
        return self._annotate_parking(row, _now())

    # -- lifecycle --------------------------------------------------------

    async def reset(self, session: AsyncSession, campus_id: str) -> None:
        """Clear all observations for a campus back to an unobserved state.
        Structural rows (one per config entity) remain; vehicles, being
        transient, are removed entirely. The campus scenario resets to
        'normal'."""

        await self._require_campus(session, campus_id)

        for row in await self._twin.list_parking_states(session, campus_id):
            row.occupied = None
            row.predicted_occupancy = None
            row.observation_timestamp = None
            row.ingestion_timestamp = None
            row.source = None
            row.provenance = None
            await session.merge(row)

        for row in await self._twin.list_gate_states(session, campus_id):
            row.queue = None
            row.throughput = None
            row.observation_timestamp = None
            row.ingestion_timestamp = None
            row.source = None
            row.provenance = None
            await session.merge(row)

        for row in await self._twin.list_road_states(session, campus_id):
            row.load = None
            row.congestion = None
            row.observation_timestamp = None
            row.ingestion_timestamp = None
            row.source = None
            row.provenance = None
            await session.merge(row)

        await session.execute(delete(VehicleState).where(VehicleState.campus_id == campus_id))

        campus_state = await session.get(CampusState, campus_id)
        if campus_state is not None:
            campus_state.active_scenario = "normal"
            await session.merge(campus_state)

        await session.commit()

    async def snapshot(self, session: AsyncSession, campus_id: str) -> TwinSnapshot:
        """Capture the current state into an immutable snapshot row. Meant
        to be invoked every 5 minutes by an external scheduler (this module
        does not run its own scheduler)."""

        state = await self.get_state(session, campus_id)
        taken_at = state["generated_at"]
        snapshot = TwinSnapshot(
            snapshot_id=f"{campus_id}:{taken_at.isoformat()}",
            campus_id=campus_id,
            taken_at=taken_at,
            payload=_json_safe(state),
        )
        await session.merge(snapshot)
        await session.commit()
        return await session.get(TwinSnapshot, snapshot.snapshot_id)

    async def get_history(self, session: AsyncSession, campus_id: str, limit: int = 50) -> list[TwinSnapshot]:
        await self._require_campus(session, campus_id)
        return await self._twin.list_snapshots(session, campus_id, limit)


def _json_safe(value):
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value
