from datetime import datetime

from pydantic import BaseModel, ConfigDict


class GateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    gate_id: str
    campus_id: str
    name: str
    latitude: float
    longitude: float
    capacity: int
    status: str
    configuration_version: int


class RoadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    road_id: str
    campus_id: str
    name: str
    start_node: str
    end_node: str
    length: float
    expected_travel_time: float
    is_walkable: bool
    is_driveable: bool
    status: str
    geometry: list[dict]
    configuration_version: int


class ParkingLotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    parking_lot_id: str
    campus_id: str
    name: str
    status: str
    camera_available: bool
    camera_notes: str | None
    total_capacity: int
    usable_capacity: int
    reserved_capacity: int
    restricted_capacity: int
    temporarily_unavailable_capacity: int
    configuration_version: int


class DestinationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    destination_id: str
    campus_id: str
    name: str
    category: str
    latitude: float
    longitude: float
    department_names: list[str]
    searchable_aliases: list[str]
    nearest_gates: list[str]
    nearest_parking_lots: list[str]
    configuration_version: int


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: str
    campus_id: str
    event_type: str
    name: str
    start_time: datetime
    end_time: datetime
    expected_demand_multiplier: float
    affected_zones: list[str]
    status: str
    configuration_version: int
