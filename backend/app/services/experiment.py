"""Module 8 — baseline strategies experiment runner.

Runs one scenario across a grid of (allocation strategy x seed), reusing
Module 7's SimulationEngine unmodified. The same seed list is used for every
strategy ("paired" across strategies) so the aggregate comparison isn't
contaminated by different strategies having faced different random demand.

Aggregation is mean / sample std-dev / 95% CI computed with a normal
(z=1.96) approximation — this project has no scipy dependency for a proper
t-distribution, and is documented as such rather than silently presented as
exact. Aggregates and raw per-(strategy, seed) results are stored together
in ExperimentRun and never hand-edited; /compare and any future charting
read only from that stored data, never recomputed from scratch elsewhere.

This is the SAME runner Module 14 (ablation/robustness/scalability) reuses
— it takes an explicit scenario, strategy list, and seed list, and makes no
assumption specific to baseline comparison.
"""

import math
import statistics
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.experiment import ExperimentRun
from app.scenario_loader.schema import ScenarioConfig
from app.services.allocation import UnknownStrategyError, build_strategy
from app.services.simulation import SimulationEngine

DEFAULT_SEEDS: list[int] = list(range(30))

Z_95 = 1.959963985  # normal-approximation critical value for a 95% CI

# metric_key -> extractor from a SimulationResult.metrics dict. Kept as a
# flat scalar view over Module 7's richer metrics, for aggregation.
_METRIC_EXTRACTORS: dict[str, Callable[[dict], float | None]] = {
    "vehicles_total": lambda m: m["vehicles_total"],
    "vehicles_parked": lambda m: m["vehicles_parked"],
    "overflow_count": lambda m: m["overflow_count"],
    "avg_search_time_minutes": lambda m: m["search_time_minutes"]["avg"],
    "avg_wait_time_minutes": lambda m: m["gate_wait_time_minutes"]["avg"],
    "avg_gate_queue_length": lambda m: m["gate_queue_length"]["avg"],
    "max_gate_queue_length": lambda m: m["gate_queue_length"]["max"],
    "total_travel_time_seconds": lambda m: m["travel_time_seconds"]["total"],
    "total_travel_distance_meters": lambda m: m["travel_distance_meters"]["total"],
}
METRIC_KEYS = tuple(_METRIC_EXTRACTORS)


def _extract_metrics(metrics: dict) -> dict[str, float | None]:
    return {key: extractor(metrics) for key, extractor in _METRIC_EXTRACTORS.items()}


def _aggregate(values: list[float]) -> dict:
    n = len(values)
    if n == 0:
        return {"mean": None, "std_dev": None, "ci_95": None, "n": 0}
    mean = statistics.fmean(values)
    if n > 1:
        std = statistics.stdev(values)
        margin = Z_95 * std / math.sqrt(n)
        ci = [round(mean - margin, 4), round(mean + margin, 4)]
    else:
        std = 0.0
        ci = None
    return {"mean": round(mean, 4), "std_dev": round(std, 4), "ci_95": ci, "n": n}


@dataclass
class ExperimentResult:
    experiment_id: str
    campus_id: str
    scenario_id: str
    strategies: list[str]
    seeds: list[int]
    started_at: datetime
    finished_at: datetime
    raw_results: list[dict] = field(default_factory=list)
    aggregated: dict = field(default_factory=dict)


class ExperimentRunner:
    def __init__(self, engine: SimulationEngine | None = None) -> None:
        self._engine = engine or SimulationEngine()

    async def run(
        self,
        session: AsyncSession,
        scenario: ScenarioConfig,
        strategy_names: list[str],
        seeds: list[int] | None = None,
    ) -> ExperimentResult:
        if not strategy_names:
            raise ValueError("at least one strategy is required")
        # Fail fast on an unknown strategy name before running anything.
        strategy_instances = {name: build_strategy(name) for name in strategy_names}

        effective_seeds = list(seeds) if seeds else list(DEFAULT_SEEDS)
        # Validate the scenario once; SimulationEngine.run() re-validates
        # per call, which is redundant but harmless and keeps this method a
        # thin loop rather than duplicating engine internals.
        await self._engine.validate(session, scenario)

        started_at = datetime.now(timezone.utc)
        raw_results: list[dict] = []
        for name in strategy_names:
            strategy = strategy_instances[name]
            for seed in effective_seeds:
                result = await self._engine.run(session, scenario, seed=seed, strategy=strategy)
                raw_results.append(
                    {
                        "strategy": name,
                        "seed": seed,
                        "run_id": result.run_id,
                        "metrics": _extract_metrics(result.metrics),
                    }
                )
        finished_at = datetime.now(timezone.utc)

        aggregated: dict[str, dict[str, dict]] = {}
        for name in strategy_names:
            entries = [r["metrics"] for r in raw_results if r["strategy"] == name]
            aggregated[name] = {
                metric_key: _aggregate([e[metric_key] for e in entries if e[metric_key] is not None])
                for metric_key in METRIC_KEYS
            }

        return ExperimentResult(
            experiment_id=f"exp_{uuid.uuid4().hex}",
            campus_id=scenario.campus_id,
            scenario_id=scenario.scenario_id,
            strategies=strategy_names,
            seeds=effective_seeds,
            started_at=started_at,
            finished_at=finished_at,
            raw_results=raw_results,
            aggregated=aggregated,
        )

    async def run_and_store(
        self,
        session: AsyncSession,
        scenario: ScenarioConfig,
        strategy_names: list[str],
        seeds: list[int] | None = None,
    ) -> ExperimentRun:
        result = await self.run(session, scenario, strategy_names, seeds)
        run = ExperimentRun(
            experiment_id=result.experiment_id,
            campus_id=result.campus_id,
            scenario_id=result.scenario_id,
            strategies=result.strategies,
            seeds=result.seeds,
            started_at=result.started_at,
            finished_at=result.finished_at,
            raw_results=result.raw_results,
            aggregated=result.aggregated,
        )
        session.add(run)
        await session.commit()
        return run


async def get_experiment(session: AsyncSession, experiment_id: str) -> ExperimentRun | None:
    return await session.get(ExperimentRun, experiment_id)


def compare_by_metric(aggregated: dict) -> dict:
    """Reshape stored {strategy: {metric: stats}} into {metric: {strategy:
    stats}} — the same stored numbers, viewed per-metric for side-by-side
    strategy comparison. Computes nothing new."""

    by_metric: dict[str, dict] = {metric_key: {} for metric_key in METRIC_KEYS}
    for strategy_name, metrics in aggregated.items():
        for metric_key, stats in metrics.items():
            by_metric.setdefault(metric_key, {})[strategy_name] = stats
    return by_metric


__all__ = [
    "DEFAULT_SEEDS",
    "METRIC_KEYS",
    "ExperimentResult",
    "ExperimentRunner",
    "UnknownStrategyError",
    "compare_by_metric",
    "get_experiment",
]
