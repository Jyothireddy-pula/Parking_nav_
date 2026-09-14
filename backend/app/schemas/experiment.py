from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ExperimentCreateRequest(BaseModel):
    # The full scenario definition (same shape as a configs/scenarios/*.yaml
    # file loaded as JSON) — kept explicit rather than a filename reference
    # so an experiment is fully reproducible from the request alone.
    scenario: dict[str, Any]
    strategies: list[str] = Field(min_length=1)
    seeds: list[int] | None = None


class MetricStatsOut(BaseModel):
    mean: float | None
    std_dev: float | None
    ci_95: list[float] | None
    n: int


class ExperimentOut(BaseModel):
    experiment_id: str
    campus_id: str
    scenario_id: str
    strategies: list[str]
    seeds: list[int]
    started_at: datetime
    finished_at: datetime
    raw_results: list[dict]
    aggregated: dict[str, dict[str, MetricStatsOut]]


class ExperimentCompareOut(BaseModel):
    experiment_id: str
    by_metric: dict[str, dict[str, MetricStatsOut]]
