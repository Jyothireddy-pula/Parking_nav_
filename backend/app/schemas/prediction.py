from typing import Literal

from pydantic import BaseModel

Horizon = Literal[15, 30]


class PredictRequest(BaseModel):
    campus_id: str
    parking_lot_id: str
    horizon_minutes: Horizon


class PredictResponseOut(BaseModel):
    point_estimate: float | None
    lower_bound: float | None
    upper_bound: float | None
    model_version: str | None
    confidence: str
