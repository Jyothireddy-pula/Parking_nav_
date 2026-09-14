from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.schemas.risk import (
    PredictionSummaryOut,
    ProactiveTriggerOut,
    RiskAssessmentOut,
    RiskComponentOut,
)
from app.services.campus_config import CampusNotFoundError
from app.services.prediction import FileModelRegistry, PredictionService
from app.services.risk import LotNotFoundError, RiskAssessment, RiskComponent, RiskEngine

router = APIRouter(tags=["risk"])

_settings = get_settings()
_prediction_service = PredictionService(FileModelRegistry(Path(_settings.prediction_model_dir)))
risk_engine = RiskEngine(_prediction_service)


def _component_out(component: RiskComponent) -> RiskComponentOut:
    return RiskComponentOut(
        available=component.available,
        level=component.level,
        raw_value=component.raw_value,
        threshold=component.threshold,
        score=component.score,
        reason=component.reason,
    )


def _to_out(assessment: RiskAssessment) -> RiskAssessmentOut:
    return RiskAssessmentOut(
        campus_id=assessment.campus_id,
        lot_id=assessment.lot_id,
        lot_status=assessment.lot_status,
        assessed_at=assessment.assessed_at,
        overflow_risk=_component_out(assessment.overflow_risk),
        gate_queue_risk=_component_out(assessment.gate_queue_risk),
        road_congestion_risk=_component_out(assessment.road_congestion_risk),
        search_risk=_component_out(assessment.search_risk),
        combined_network_risk=_component_out(assessment.combined_network_risk),
        proactive_trigger=ProactiveTriggerOut(
            fired=assessment.proactive_trigger.fired,
            reason=assessment.proactive_trigger.reason,
            current_occupancy_pct=assessment.proactive_trigger.current_occupancy_pct,
            predicted_upper_bound_pct=assessment.proactive_trigger.predicted_upper_bound_pct,
            threshold_pct=assessment.proactive_trigger.threshold_pct,
        ),
        prediction=(
            PredictionSummaryOut(
                point_estimate=assessment.prediction.point_estimate,
                lower_bound=assessment.prediction.lower_bound,
                upper_bound=assessment.prediction.upper_bound,
                model_version=assessment.prediction.model_version,
                confidence=assessment.prediction.confidence,
                horizon_minutes=assessment.prediction.horizon_minutes,
            )
            if assessment.prediction is not None
            else None
        ),
        excluded_from_combined=assessment.excluded_from_combined,
    )


@router.get("/risk/{lot_id}", response_model=RiskAssessmentOut)
async def get_risk(
    lot_id: str,
    campus_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RiskAssessmentOut:
    try:
        assessment = await risk_engine.assess(session, campus_id, lot_id)
    except CampusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"campus {campus_id!r} not found") from exc
    except LotNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return _to_out(assessment)
