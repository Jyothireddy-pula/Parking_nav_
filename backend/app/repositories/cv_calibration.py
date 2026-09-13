from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cv_calibration import CvCalibrationReport


class CvCalibrationRepository:
    async def list_reports(
        self, session: AsyncSession, campus_id: str, parking_lot_id: str | None = None
    ) -> list[CvCalibrationReport]:
        stmt = select(CvCalibrationReport).where(CvCalibrationReport.campus_id == campus_id)
        if parking_lot_id is not None:
            stmt = stmt.where(CvCalibrationReport.parking_lot_id == parking_lot_id)
        stmt = stmt.order_by(CvCalibrationReport.timestamp.desc())
        result = await session.execute(stmt)
        return list(result.scalars().all())
