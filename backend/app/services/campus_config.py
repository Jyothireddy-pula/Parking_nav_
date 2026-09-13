from sqlalchemy.ext.asyncio import AsyncSession

from app.models.destination import Destination
from app.models.event import Event
from app.models.gate import Gate
from app.models.parking_lot import ParkingLot
from app.models.road import Road
from app.repositories.campus_config import CampusConfigRepository


class CampusNotFoundError(Exception):
    def __init__(self, campus_id: str) -> None:
        self.campus_id = campus_id
        super().__init__(f"campus {campus_id!r} not found")


class CampusConfigService:
    def __init__(self, repository: CampusConfigRepository | None = None) -> None:
        self._repository = repository or CampusConfigRepository()

    async def _require_campus(self, session: AsyncSession, campus_id: str) -> None:
        campus = await self._repository.get_campus(session, campus_id)
        if campus is None:
            raise CampusNotFoundError(campus_id)

    async def get_gates(self, session: AsyncSession, campus_id: str) -> list[Gate]:
        await self._require_campus(session, campus_id)
        return await self._repository.list_gates(session, campus_id)

    async def get_roads(self, session: AsyncSession, campus_id: str) -> list[Road]:
        await self._require_campus(session, campus_id)
        return await self._repository.list_roads(session, campus_id)

    async def get_parking_lots(self, session: AsyncSession, campus_id: str) -> list[ParkingLot]:
        await self._require_campus(session, campus_id)
        return await self._repository.list_parking_lots(session, campus_id)

    async def get_destinations(self, session: AsyncSession, campus_id: str) -> list[Destination]:
        await self._require_campus(session, campus_id)
        return await self._repository.list_destinations(session, campus_id)

    async def get_events(self, session: AsyncSession, campus_id: str) -> list[Event]:
        await self._require_campus(session, campus_id)
        return await self._repository.list_events(session, campus_id)
