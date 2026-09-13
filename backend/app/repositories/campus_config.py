from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campus import Campus
from app.models.destination import Destination
from app.models.event import Event
from app.models.gate import Gate
from app.models.parking_lot import ParkingLot
from app.models.road import Road


class CampusConfigRepository:
    async def get_campus(self, session: AsyncSession, campus_id: str) -> Campus | None:
        return await session.get(Campus, campus_id)

    async def list_gates(self, session: AsyncSession, campus_id: str) -> list[Gate]:
        result = await session.execute(select(Gate).where(Gate.campus_id == campus_id).order_by(Gate.gate_id))
        return list(result.scalars().all())

    async def list_roads(self, session: AsyncSession, campus_id: str) -> list[Road]:
        result = await session.execute(select(Road).where(Road.campus_id == campus_id).order_by(Road.road_id))
        return list(result.scalars().all())

    async def list_parking_lots(self, session: AsyncSession, campus_id: str) -> list[ParkingLot]:
        result = await session.execute(
            select(ParkingLot).where(ParkingLot.campus_id == campus_id).order_by(ParkingLot.parking_lot_id)
        )
        return list(result.scalars().all())

    async def list_destinations(self, session: AsyncSession, campus_id: str) -> list[Destination]:
        result = await session.execute(
            select(Destination).where(Destination.campus_id == campus_id).order_by(Destination.destination_id)
        )
        return list(result.scalars().all())

    async def list_events(self, session: AsyncSession, campus_id: str) -> list[Event]:
        result = await session.execute(select(Event).where(Event.campus_id == campus_id).order_by(Event.event_id))
        return list(result.scalars().all())
