from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ObservationIn(BaseModel):
    """Deliberately permissive: negative counts, out-of-range intensities,
    and other semantic problems are NOT rejected here at the schema level.
    They're recorded into observations_raw first (immutable, whatever was
    submitted) and only then rejected by the ingestion service's business
    validation into observations_rejected, with a reason. Rejecting at the
    pydantic layer would mean the bad row was never actually recorded."""

    timestamp: datetime
    gate_id: str | None = None
    vehicle_count: int | None = None
    parking_lot_id: str | None = None
    occupied_spaces: int | None = None
    event_type: str | None = None
    event_intensity: float | None = None
    notes: str | None = None
    source_label: str
    collection_method: str


class ObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    observation_id: str
    campus_id: str
    timestamp: datetime
    gate_id: str | None
    vehicle_count: int | None
    parking_lot_id: str | None
    occupied_spaces: int | None
    event_type: str | None
    event_intensity: float | None
    notes: str | None
    source_label: str
    collection_method: str
    batch_id: str | None
    data_quality_flags: list[str]


class ObservationRejectedOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rejection_id: str
    campus_id: str
    timestamp: datetime
    gate_id: str | None
    vehicle_count: int | None
    parking_lot_id: str | None
    occupied_spaces: int | None
    event_type: str | None
    event_intensity: float | None
    notes: str | None
    source_label: str
    collection_method: str
    batch_id: str | None
    reason: str


class IngestionBatchResultOut(BaseModel):
    batch_id: str
    campus_id: str
    submitted_via: str
    total_rows: int
    accepted_rows: int
    rejected_rows: int
    accepted: list[ObservationOut]
    rejected: list[ObservationRejectedOut]


class QualityReportOut(BaseModel):
    campus_id: str
    raw_total: int
    accepted_total: int
    rejected_total: int
    rejection_reason_counts: dict[str, int]
    accepted_by_collection_method: dict[str, int]
    coverage: dict[str, int]
