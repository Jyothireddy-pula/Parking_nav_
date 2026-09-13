from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class HealthRepository:
    async def database_is_available(self, session: AsyncSession) -> bool:
        await session.execute(text("SELECT 1"))
        return True
