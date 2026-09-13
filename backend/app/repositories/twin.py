from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.twin import (
    CampusState,
    GateState,
    ParkingState,
    RoadState,
    TwinSnapshot,
    VehicleState,
)


class TwinRepository:
    async def get_campus_state(self, session: AsyncSession, campus_id: str) -> CampusState | None:
        return await session.get(CampusState, campus_id)

    async def get_parking_state(self, session: AsyncSession, lot_id: str) -> ParkingState | None:
        return await session.get(ParkingState, lot_id)

    async def get_gate_state(self, session: AsyncSession, gate_id: str) -> GateState | None:
        return await session.get(GateState, gate_id)

    async def get_road_state(self, session: AsyncSession, road_id: str) -> RoadState | None:
        return await session.get(RoadState, road_id)

    async def get_vehicle_state(self, session: AsyncSession, vehicle_id: str) -> VehicleState | None:
        return await session.get(VehicleState, vehicle_id)

    async def list_parking_states(self, session: AsyncSession, campus_id: str) -> list[ParkingState]:
        result = await session.execute(
            select(ParkingState).where(ParkingState.campus_id == campus_id).order_by(ParkingState.parking_lot_id)
        )
        return list(result.scalars().all())

    async def list_gate_states(self, session: AsyncSession, campus_id: str) -> list[GateState]:
        result = await session.execute(
            select(GateState).where(GateState.campus_id == campus_id).order_by(GateState.gate_id)
        )
        return list(result.scalars().all())

    async def list_road_states(self, session: AsyncSession, campus_id: str) -> list[RoadState]:
        result = await session.execute(
            select(RoadState).where(RoadState.campus_id == campus_id).order_by(RoadState.road_id)
        )
        return list(result.scalars().all())

    async def list_vehicle_states(self, session: AsyncSession, campus_id: str) -> list[VehicleState]:
        result = await session.execute(
            select(VehicleState).where(VehicleState.campus_id == campus_id).order_by(VehicleState.vehicle_id)
        )
        return list(result.scalars().all())

    async def list_snapshots(
        self, session: AsyncSession, campus_id: str, limit: int = 50
    ) -> list[TwinSnapshot]:
        result = await session.execute(
            select(TwinSnapshot)
            .where(TwinSnapshot.campus_id == campus_id)
            .order_by(TwinSnapshot.taken_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
