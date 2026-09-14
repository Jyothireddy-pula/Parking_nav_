from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ENTITY_TYPES = ("gate", "parking_lot", "road")
OVERRIDE_STATUSES = ("closed", "restricted")


class ArrivalRateEntry(BaseModel):
    gate_id: str
    start_minute: int = Field(ge=0)
    end_minute: int = Field(ge=0)
    vehicles_per_minute: float = Field(ge=0)

    @model_validator(mode="after")
    def _end_after_start(self) -> "ArrivalRateEntry":
        if self.end_minute <= self.start_minute:
            raise ValueError(
                f"arrival_rate_profile entry for gate {self.gate_id!r}: end_minute must be after start_minute"
            )
        return self


class EventCondition(BaseModel):
    name: str
    start_minute: int = Field(ge=0)
    end_minute: int = Field(ge=0)
    # An explicit ASSUMPTION applied to arrival rates during this window —
    # never presented as a measured fact.
    demand_multiplier: float = Field(gt=0)

    @model_validator(mode="after")
    def _end_after_start(self) -> "EventCondition":
        if self.end_minute <= self.start_minute:
            raise ValueError(f"event_condition {self.name!r}: end_minute must be after start_minute")
        return self


class AvailabilityOverride(BaseModel):
    entity_type: str
    entity_id: str
    status: str
    start_minute: int = Field(ge=0)
    end_minute: int = Field(ge=0)

    @field_validator("entity_type")
    @classmethod
    def _valid_entity_type(cls, value: str) -> str:
        if value not in ENTITY_TYPES:
            raise ValueError(f"entity_type must be one of {ENTITY_TYPES}, got {value!r}")
        return value

    @field_validator("status")
    @classmethod
    def _valid_status(cls, value: str) -> str:
        if value not in OVERRIDE_STATUSES:
            raise ValueError(f"status must be one of {OVERRIDE_STATUSES}, got {value!r}")
        return value

    @model_validator(mode="after")
    def _end_after_start(self) -> "AvailabilityOverride":
        if self.end_minute <= self.start_minute:
            raise ValueError(
                f"availability_override for {self.entity_type} {self.entity_id!r}: "
                "end_minute must be after start_minute"
            )
        return self


class CapacityOverride(BaseModel):
    parking_lot_id: str
    total_capacity: int = Field(ge=0)
    usable_capacity: int = Field(ge=0)

    @model_validator(mode="after")
    def _usable_fits_total(self) -> "CapacityOverride":
        if self.usable_capacity > self.total_capacity:
            raise ValueError(
                f"capacity_override for {self.parking_lot_id!r}: usable_capacity exceeds total_capacity"
            )
        return self


class ScenarioConfig(BaseModel):
    scenario_id: str
    campus_id: str
    name: str
    description: str | None = None
    # Always SYNTHETIC — a scenario is a simulator input, never a measured
    # fact, no matter how realistic its numbers look.
    label: Literal["SYNTHETIC"] = "SYNTHETIC"
    duration_minutes: int = Field(gt=0)
    seed: int = 0
    # 0 = the allocation strategy sees exact live state; 1 = maximally
    # noisy. Applied as seeded Gaussian jitter on occupancy readings the
    # strategy is given — not on ground truth, which the engine always
    # tracks exactly for the capacity-never-exceeded guarantee.
    prediction_error_level: float = Field(ge=0, le=1, default=0.0)

    arrival_rate_profile: list[ArrivalRateEntry] = Field(default_factory=list)
    event_conditions: list[EventCondition] = Field(default_factory=list)
    availability_overrides: list[AvailabilityOverride] = Field(default_factory=list)
    capacity_overrides: list[CapacityOverride] = Field(default_factory=list)
