from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.destination import DESTINATION_CATEGORIES
from app.models.event import EVENT_STATUSES
from app.models.gate import GATE_STATUSES
from app.models.parking_lot import PARKING_LOT_STATUSES
from app.models.provenance import CONFIG_PROVENANCE_LABELS
from app.models.road import ROAD_STATUSES


class Coordinates(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class GateConfig(BaseModel):
    gate_id: str
    name: str
    coordinates: Coordinates
    capacity: int = Field(ge=0)
    status: str = "open"
    provenance: str

    @field_validator("status")
    @classmethod
    def _valid_status(cls, value: str) -> str:
        if value not in GATE_STATUSES:
            raise ValueError(f"gate status must be one of {GATE_STATUSES}, got {value!r}")
        return value

    @field_validator("provenance")
    @classmethod
    def _valid_provenance(cls, value: str) -> str:
        if value not in CONFIG_PROVENANCE_LABELS:
            raise ValueError(f"provenance must be one of {CONFIG_PROVENANCE_LABELS}, got {value!r}")
        return value


class RoadConfig(BaseModel):
    road_id: str
    name: str
    start_node: str
    end_node: str
    length: float = Field(gt=0)
    expected_travel_time: float = Field(ge=0)
    is_walkable: bool = False
    is_driveable: bool = False
    status: str = "open"
    geometry: list[Coordinates]
    provenance: str

    @field_validator("status")
    @classmethod
    def _valid_status(cls, value: str) -> str:
        if value not in ROAD_STATUSES:
            raise ValueError(f"road status must be one of {ROAD_STATUSES}, got {value!r}")
        return value

    @field_validator("provenance")
    @classmethod
    def _valid_provenance(cls, value: str) -> str:
        if value not in CONFIG_PROVENANCE_LABELS:
            raise ValueError(f"provenance must be one of {CONFIG_PROVENANCE_LABELS}, got {value!r}")
        return value

    @model_validator(mode="after")
    def _geometry_is_a_real_path(self) -> "RoadConfig":
        if len(self.geometry) < 3:
            raise ValueError(
                f"road {self.road_id!r} geometry must contain more than the two endpoints "
                "(a walked/driven path survey), got "
                f"{len(self.geometry)} point(s)"
            )
        return self

    @model_validator(mode="after")
    def _at_least_one_mode(self) -> "RoadConfig":
        if not self.is_walkable and not self.is_driveable:
            raise ValueError(f"road {self.road_id!r} must be walkable, driveable, or both")
        return self


class ParkingLotConfig(BaseModel):
    parking_lot_id: str
    name: str
    status: str = "open"
    camera_available: bool = False
    camera_notes: str | None = None
    total_capacity: int = Field(ge=0)
    usable_capacity: int = Field(ge=0)
    reserved_capacity: int = Field(ge=0, default=0)
    restricted_capacity: int = Field(ge=0, default=0)
    temporarily_unavailable_capacity: int = Field(ge=0, default=0)
    # Walked perimeter + center point from Module 1B's GPS survey. Optional:
    # not every lot has been surveyed yet.
    center: Coordinates | None = None
    geometry: list[Coordinates] | None = None
    provenance: str

    @field_validator("status")
    @classmethod
    def _valid_status(cls, value: str) -> str:
        if value not in PARKING_LOT_STATUSES:
            raise ValueError(f"parking lot status must be one of {PARKING_LOT_STATUSES}, got {value!r}")
        return value

    @field_validator("provenance")
    @classmethod
    def _valid_provenance(cls, value: str) -> str:
        if value not in CONFIG_PROVENANCE_LABELS:
            raise ValueError(f"provenance must be one of {CONFIG_PROVENANCE_LABELS}, got {value!r}")
        if value == "EXTERNAL_MAP_REFERENCE":
            raise ValueError(
                "parking lot capacity can never come from a map source — provenance must be "
                "REAL (physical count) or SAMPLE, never EXTERNAL_MAP_REFERENCE"
            )
        return value

    @model_validator(mode="after")
    def _perimeter_is_a_real_boundary(self) -> "ParkingLotConfig":
        if self.geometry is not None and len(self.geometry) < 4:
            raise ValueError(
                f"parking lot {self.parking_lot_id!r} geometry must contain at least 4 walked "
                f"perimeter points, got {len(self.geometry)}"
            )
        return self

    @model_validator(mode="after")
    def _capacity_breakdown_fits_total(self) -> "ParkingLotConfig":
        allocated = (
            self.usable_capacity
            + self.reserved_capacity
            + self.restricted_capacity
            + self.temporarily_unavailable_capacity
        )
        if allocated > self.total_capacity:
            raise ValueError(
                f"parking lot {self.parking_lot_id!r} capacity breakdown ({allocated}) "
                f"exceeds total_capacity ({self.total_capacity})"
            )
        return self


class DestinationConfig(BaseModel):
    destination_id: str
    name: str
    category: str
    coordinates: Coordinates
    department_names: list[str] = Field(default_factory=list)
    searchable_aliases: list[str] = Field(default_factory=list)
    nearest_gates: list[str] = Field(default_factory=list)
    nearest_parking_lots: list[str] = Field(default_factory=list)
    provenance: str

    @field_validator("category")
    @classmethod
    def _valid_category(cls, value: str) -> str:
        if value not in DESTINATION_CATEGORIES:
            raise ValueError(f"destination category must be one of {DESTINATION_CATEGORIES}, got {value!r}")
        return value

    @field_validator("provenance")
    @classmethod
    def _valid_provenance(cls, value: str) -> str:
        if value not in CONFIG_PROVENANCE_LABELS:
            raise ValueError(f"provenance must be one of {CONFIG_PROVENANCE_LABELS}, got {value!r}")
        return value


class EventConfig(BaseModel):
    event_id: str
    event_type: str
    name: str
    start_time: datetime
    end_time: datetime
    expected_demand_multiplier: float = Field(gt=0)
    affected_zones: list[str] = Field(default_factory=list)
    status: str = "scheduled"

    @field_validator("status")
    @classmethod
    def _valid_status(cls, value: str) -> str:
        if value not in EVENT_STATUSES:
            raise ValueError(f"event status must be one of {EVENT_STATUSES}, got {value!r}")
        return value

    @model_validator(mode="after")
    def _end_after_start(self) -> "EventConfig":
        if self.end_time <= self.start_time:
            raise ValueError(f"event {self.event_id!r} end_time must be after start_time")
        return self


class CampusConfigFile(BaseModel):
    campus_id: str
    name: str
    description: str | None = None
    timezone: str
    gates: list[GateConfig] = Field(default_factory=list)
    roads: list[RoadConfig] = Field(default_factory=list)
    parking_lots: list[ParkingLotConfig] = Field(default_factory=list)
    destinations: list[DestinationConfig] = Field(default_factory=list)
    events: list[EventConfig] = Field(default_factory=list)
