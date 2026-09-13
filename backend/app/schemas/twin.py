from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ParkingStateOut(BaseModel):
    parking_lot_id: str
    campus_id: str
    total_capacity: int
    usable_capacity: int
    reserved_capacity: int
    restricted_capacity: int
    temporarily_unavailable_capacity: int
    occupied: int | None
    available: int | None
    occupancy_pct: float | None
    predicted_occupancy: float | None
    status: str
    observation_timestamp: datetime | None
    ingestion_timestamp: datetime | None
    source: str | None
    provenance: str | None
    freshness: str


class GateStateOut(BaseModel):
    gate_id: str
    campus_id: str
    queue: int | None
    throughput: float | None
    status: str
    observation_timestamp: datetime | None
    ingestion_timestamp: datetime | None
    source: str | None
    provenance: str | None
    freshness: str


class RoadStateOut(BaseModel):
    road_id: str
    campus_id: str
    load: float | None
    congestion: str | None
    status: str
    observation_timestamp: datetime | None
    ingestion_timestamp: datetime | None
    source: str | None
    provenance: str | None
    freshness: str


class VehicleStateOut(BaseModel):
    vehicle_id: str
    campus_id: str
    state: str
    assigned_parking_lot_id: str | None
    observation_timestamp: datetime | None
    ingestion_timestamp: datetime | None
    source: str | None
    provenance: str | None
    freshness: str


class TwinStateOut(BaseModel):
    campus_id: str
    active_scenario: str | None
    config_version: int | None
    parking: list[ParkingStateOut]
    gates: list[GateStateOut]
    roads: list[RoadStateOut]
    vehicles: list[VehicleStateOut]
    generated_at: datetime


class TwinSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    snapshot_id: str
    campus_id: str
    taken_at: datetime
    payload: dict
