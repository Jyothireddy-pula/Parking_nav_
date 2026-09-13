from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.health import HealthRepository


class HealthService:
    def __init__(self, repository: HealthRepository | None = None) -> None:
        self.repository = repository or HealthRepository()

    async def check(self, session: AsyncSession) -> dict[str, str]:
        database_status = "ok"
        try:
            await self.repository.database_is_available(session)
        except SQLAlchemyError:
            database_status = "unavailable"
        return {"status": "ok", "database": database_status}
