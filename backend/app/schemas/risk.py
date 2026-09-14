from datetime import datetime

from pydantic import BaseModel


class RiskComponentOut(BaseModel):
    available: bool
    level: str
    raw_value: float | None
    threshold: float | None
    score: float | None
    reason: str | None


class ProactiveTriggerOut(BaseModel):
    fired: bool
    reason: str
    current_occupancy_pct: float | None
    predicted_upper_bound_pct: float | None
    threshold_pct: float


class PredictionSummaryOut(BaseModel):
    point_estimate: float | None
    lower_bound: float | None
    upper_bound: float | None
    model_version: str | None
    confidence: str
    horizon_minutes: int


class RiskAssessmentOut(BaseModel):
    campus_id: str
    lot_id: str
    lot_status: str
    assessed_at: datetime
    overflow_risk: RiskComponentOut
    gate_queue_risk: RiskComponentOut
    road_congestion_risk: RiskComponentOut
    search_risk: RiskComponentOut
    combined_network_risk: RiskComponentOut
    proactive_trigger: ProactiveTriggerOut
    prediction: PredictionSummaryOut | None
    excluded_from_combined: list[str]
