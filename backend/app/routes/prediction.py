from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.schemas.prediction import PredictRequest, PredictResponseOut
from app.services.campus_config import CampusNotFoundError
from app.services.prediction import FileModelRegistry, PredictionService

router = APIRouter(tags=["prediction"])

_settings = get_settings()
_registry = FileModelRegistry(Path(_settings.prediction_model_dir))
prediction_service = PredictionService(_registry)


@router.post("/predict", response_model=PredictResponseOut)
async def predict(
    request: PredictRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PredictResponseOut:
    try:
        result = await prediction_service.predict(
            session, request.campus_id, request.parking_lot_id, request.horizon_minutes
        )
    except CampusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"campus {request.campus_id!r} not found") from exc

    return PredictResponseOut(
        point_estimate=result.point_estimate,
        lower_bound=result.lower_bound,
        upper_bound=result.upper_bound,
        model_version=result.model_version,
        confidence=result.confidence,
    )
