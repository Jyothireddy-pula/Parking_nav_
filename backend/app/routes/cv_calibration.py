from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.cv_calibration import CvCalibrationReportOut
from app.services.campus_config import CampusNotFoundError
from app.services.cv_calibration import (
    CvCalibrationService,
    InsufficientPairedDataError,
    ParkingLotNotFoundError,
)

router = APIRouter(tags=["cv-calibration"])
cv_calibration_service = CvCalibrationService()


@router.post(
    "/campuses/{campus_id}/parking-lots/{parking_lot_id}/cv-calibration-reports",
    response_model=CvCalibrationReportOut,
    status_code=201,
)
async def create_calibration_report(
    campus_id: str, parking_lot_id: str, session: Annotated[AsyncSession, Depends(get_db)]
) -> CvCalibrationReportOut:
    try:
        report = await cv_calibration_service.compute_calibration_report(session, campus_id, parking_lot_id)
    except CampusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"campus {campus_id!r} not found") from exc
    except ParkingLotNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InsufficientPairedDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CvCalibrationReportOut.model_validate(report)


@router.get(
    "/campuses/{campus_id}/cv-calibration-reports",
    response_model=list[CvCalibrationReportOut],
)
async def list_calibration_reports(
    campus_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    parking_lot_id: str | None = None,
) -> list[CvCalibrationReportOut]:
    try:
        reports = await cv_calibration_service.list_reports(session, campus_id, parking_lot_id)
    except CampusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"campus {campus_id!r} not found") from exc
    return [CvCalibrationReportOut.model_validate(report) for report in reports]
