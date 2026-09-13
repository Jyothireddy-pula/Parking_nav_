from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.health import HealthService

router = APIRouter(tags=["health"])
health_service = HealthService()


@router.get("/health")
async def health(session: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, str]:
    return await health_service.check(session)
