from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CvCalibrationReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    report_id: str
    campus_id: str
    parking_lot_id: str
    sample_size: int
    mae: float
    recommended_collection_method: str
    timestamp: datetime
