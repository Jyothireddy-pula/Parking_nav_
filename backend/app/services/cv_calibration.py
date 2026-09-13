"""Module 5's calibration report: measures the CV classifier's error
against Module 2's manual ground-truth counts for one lot, and applies
the documented promotion rule (never an assumption) to decide whether
that lot's CV readings can be trusted as cv_auto or must stay
cv_verified.

CV_AUTO_PROMOTION_THRESHOLD_FRACTION must match ml/cv/promotion.py's
constant of the same name — see test_cv_calibration.py, which asserts
they're equal so the two can't silently drift apart. It's duplicated
rather than imported because the backend and ml packages are installed
independently and don't share a runtime.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cv_calibration import CvCalibrationReport
from app.models.ingestion import Observation
from app.repositories.campus_config import CampusConfigRepository
from app.repositories.cv_calibration import CvCalibrationRepository
from app.services.campus_config import CampusNotFoundError

CV_AUTO_PROMOTION_THRESHOLD_FRACTION = 0.10

CV_AUTO = "cv_auto"
CV_VERIFIED = "cv_verified"

CV_COLLECTION_METHODS = ("cv_auto", "cv_verified")


class ParkingLotNotFoundError(Exception):
    def __init__(self, campus_id: str, parking_lot_id: str) -> None:
        self.campus_id = campus_id
        self.parking_lot_id = parking_lot_id
        super().__init__(f"parking_lot {parking_lot_id!r} not found in campus {campus_id!r}")


class InsufficientPairedDataError(Exception):
    def __init__(self, campus_id: str, parking_lot_id: str) -> None:
        self.campus_id = campus_id
        self.parking_lot_id = parking_lot_id
        super().__init__(
            f"no paired manual/cv observations found for campus {campus_id!r}, lot {parking_lot_id!r}"
        )


def decide_collection_method(mae: float, total_capacity: int) -> str:
    if total_capacity <= 0:
        raise ValueError(f"total_capacity must be > 0, got {total_capacity}")
    if mae < 0:
        raise ValueError(f"mae must be >= 0, got {mae}")
    threshold = CV_AUTO_PROMOTION_THRESHOLD_FRACTION * total_capacity
    return CV_AUTO if mae < threshold else CV_VERIFIED


class CvCalibrationService:
    def __init__(
        self,
        config_repository: CampusConfigRepository | None = None,
        calibration_repository: CvCalibrationRepository | None = None,
    ) -> None:
        self._config = config_repository or CampusConfigRepository()
        self._calibration = calibration_repository or CvCalibrationRepository()

    async def list_reports(
        self, session: AsyncSession, campus_id: str, parking_lot_id: str | None = None
    ) -> list[CvCalibrationReport]:
        campus = await self._config.get_campus(session, campus_id)
        if campus is None:
            raise CampusNotFoundError(campus_id)
        return await self._calibration.list_reports(session, campus_id, parking_lot_id)

    async def compute_calibration_report(
        self, session: AsyncSession, campus_id: str, parking_lot_id: str
    ) -> CvCalibrationReport:
        campus = await self._config.get_campus(session, campus_id)
        if campus is None:
            raise CampusNotFoundError(campus_id)

        lots = await self._config.list_parking_lots(session, campus_id)
        lot = next((lot for lot in lots if lot.parking_lot_id == parking_lot_id), None)
        if lot is None:
            raise ParkingLotNotFoundError(campus_id, parking_lot_id)

        manual_result = await session.execute(
            select(Observation.timestamp, Observation.occupied_spaces).where(
                Observation.campus_id == campus_id,
                Observation.parking_lot_id == parking_lot_id,
                Observation.collection_method == "manual_count",
            )
        )
        manual_by_timestamp = {row.timestamp: row.occupied_spaces for row in manual_result.all()}

        cv_result = await session.execute(
            select(Observation.timestamp, Observation.occupied_spaces).where(
                Observation.campus_id == campus_id,
                Observation.parking_lot_id == parking_lot_id,
                Observation.collection_method.in_(CV_COLLECTION_METHODS),
            )
        )
        cv_by_timestamp = {row.timestamp: row.occupied_spaces for row in cv_result.all()}

        paired_timestamps = sorted(set(manual_by_timestamp) & set(cv_by_timestamp))
        if not paired_timestamps:
            raise InsufficientPairedDataError(campus_id, parking_lot_id)

        absolute_errors = [
            abs(manual_by_timestamp[ts] - cv_by_timestamp[ts]) for ts in paired_timestamps
        ]
        mae = sum(absolute_errors) / len(absolute_errors)
        recommended_method = decide_collection_method(mae, lot.total_capacity)

        report = CvCalibrationReport(
            report_id=f"cvcal_{uuid.uuid4().hex}",
            campus_id=campus_id,
            parking_lot_id=parking_lot_id,
            sample_size=len(paired_timestamps),
            mae=mae,
            recommended_collection_method=recommended_method,
            timestamp=datetime.now(timezone.utc),
        )
        session.add(report)
        await session.commit()
        return report
