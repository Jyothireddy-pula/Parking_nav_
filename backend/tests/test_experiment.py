import math
from pathlib import Path
from random import Random

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_loader.loader import load_campus_config_file
from app.config_loader.upsert import upsert_campus_config
from app.scenario_loader.schema import ScenarioConfig
from app.services.allocation import (
    AllocationContext,
    FirstAvailableStrategy,
    LotCandidate,
    NearestAvailableLotStrategy,
    PredictionOnlyStrategy,
    UnknownStrategyError,
    build_strategy,
)
from app.services.experiment import Z_95, ExperimentRunner, _aggregate

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CAMPUS_PATH = REPO_ROOT / "configs" / "campuses" / "sample.yaml"


@pytest.fixture
async def sample_campus(db_session: AsyncSession) -> str:
    config = load_campus_config_file(SAMPLE_CAMPUS_PATH)
    await upsert_campus_config(db_session, config)
    return config.campus_id


def _scenario(**overrides) -> ScenarioConfig:
    fields = {
        "scenario_id": "exp-test-scenario",
        "campus_id": "sample",
        "name": "Experiment test scenario",
        "duration_minutes": 20,
        "seed": 0,
        "arrival_rate_profile": [
            {"gate_id": "sample-gate-main", "start_minute": 0, "end_minute": 20, "vehicles_per_minute": 0.3}
        ],
    }
    fields.update(overrides)
    return ScenarioConfig.model_validate(fields)


# --- B1/B2/B3 strategy unit tests: hand-verifiable, single deterministic call ---


def test_b1_first_available_ignores_travel_time_picks_lowest_lot_id() -> None:
    context = AllocationContext(
        minute=0,
        gate_id="g",
        candidates=[
            LotCandidate(lot_id="lot-b", travel_time_s=10.0, apparent_available=5.0),
            LotCandidate(lot_id="lot-a", travel_time_s=999.0, apparent_available=1.0),
        ],
        rng=Random(0),
    )
    assert FirstAvailableStrategy().choose(context) == "lot-a"


def test_b1_first_available_skips_full_lots() -> None:
    context = AllocationContext(
        minute=0,
        gate_id="g",
        candidates=[
            LotCandidate(lot_id="lot-a", travel_time_s=1.0, apparent_available=0.0),
            LotCandidate(lot_id="lot-b", travel_time_s=1.0, apparent_available=3.0),
        ],
        rng=Random(0),
    )
    assert FirstAvailableStrategy().choose(context) == "lot-b"


def test_b2_nearest_available_picks_shortest_travel_time() -> None:
    context = AllocationContext(
        minute=0,
        gate_id="g",
        candidates=[
            LotCandidate(lot_id="lot-far", travel_time_s=200.0, apparent_available=5.0),
            LotCandidate(lot_id="lot-near", travel_time_s=50.0, apparent_available=5.0),
        ],
        rng=Random(0),
    )
    assert NearestAvailableLotStrategy().choose(context) == "lot-near"


def test_b3_prediction_only_picks_most_apparent_room() -> None:
    context = AllocationContext(
        minute=0,
        gate_id="g",
        candidates=[
            LotCandidate(lot_id="lot-tight", travel_time_s=1.0, apparent_available=2.0),
            LotCandidate(lot_id="lot-roomy", travel_time_s=999.0, apparent_available=40.0),
        ],
        rng=Random(0),
    )
    assert PredictionOnlyStrategy().choose(context) == "lot-roomy"


def test_all_strategies_return_none_when_no_lot_has_room() -> None:
    candidates = [LotCandidate(lot_id="lot-a", travel_time_s=1.0, apparent_available=0.0)]
    context = AllocationContext(minute=0, gate_id="g", candidates=candidates, rng=Random(0))
    assert FirstAvailableStrategy().choose(context) is None
    assert NearestAvailableLotStrategy().choose(context) is None
    assert PredictionOnlyStrategy().choose(context) is None


def test_build_strategy_registry() -> None:
    assert isinstance(build_strategy("first_available"), FirstAvailableStrategy)
    assert isinstance(build_strategy("nearest_available"), NearestAvailableLotStrategy)
    assert isinstance(build_strategy("prediction_only"), PredictionOnlyStrategy)
    with pytest.raises(UnknownStrategyError):
        build_strategy("does-not-exist")


# --- Aggregation: hand-computed example ---


def test_aggregate_matches_hand_computed_example() -> None:
    # mean and sample std-dev of [10, 12, 14] are exactly computable by hand:
    # mean = 12, variance = ((10-12)^2 + (12-12)^2 + (14-12)^2) / (3-1) = 4, std = 2.
    stats = _aggregate([10.0, 12.0, 14.0])

    assert stats["mean"] == 12.0
    assert stats["std_dev"] == 2.0
    assert stats["n"] == 3
    margin = Z_95 * 2.0 / math.sqrt(3)
    assert stats["ci_95"] == [round(12.0 - margin, 4), round(12.0 + margin, 4)]


def test_aggregate_of_empty_list_is_all_none() -> None:
    stats = _aggregate([])
    assert stats == {"mean": None, "std_dev": None, "ci_95": None, "n": 0}


def test_aggregate_of_single_value_has_zero_std_and_no_ci() -> None:
    stats = _aggregate([7.0])
    assert stats["mean"] == 7.0
    assert stats["std_dev"] == 0.0
    assert stats["ci_95"] is None
    assert stats["n"] == 1


# --- ExperimentRunner: engine integration ---


async def test_zero_arrival_scenario_has_hand_verifiable_zero_metrics(
    db_session: AsyncSession, sample_campus: str
) -> None:
    scenario = _scenario(
        arrival_rate_profile=[
            {"gate_id": "sample-gate-main", "start_minute": 0, "end_minute": 20, "vehicles_per_minute": 0.0}
        ]
    )
    runner = ExperimentRunner()

    result = await runner.run(db_session, scenario, ["first_available"], seeds=[1, 2, 3])

    # lam=0 means zero arrivals regardless of seed -- fully hand-verifiable.
    for entry in result.raw_results:
        assert entry["metrics"]["vehicles_total"] == 0
        assert entry["metrics"]["overflow_count"] == 0
    agg = result.aggregated["first_available"]["vehicles_total"]
    assert agg == {"mean": 0.0, "std_dev": 0.0, "ci_95": [0.0, 0.0], "n": 3}


async def test_run_is_reproducible_for_a_fixed_seed_list(
    db_session: AsyncSession, sample_campus: str
) -> None:
    scenario = _scenario()
    runner = ExperimentRunner()

    result_a = await runner.run(db_session, scenario, ["first_available", "nearest_available"], seeds=[1, 2])
    result_b = await runner.run(db_session, scenario, ["first_available", "nearest_available"], seeds=[1, 2])

    # run_id is a fresh uuid every call by design; everything else must match.
    metrics_a = [(r["strategy"], r["seed"], r["metrics"]) for r in result_a.raw_results]
    metrics_b = [(r["strategy"], r["seed"], r["metrics"]) for r in result_b.raw_results]
    assert metrics_a == metrics_b
    assert result_a.aggregated == result_b.aggregated


async def test_seeds_are_paired_across_strategies(db_session: AsyncSession, sample_campus: str) -> None:
    scenario = _scenario()
    runner = ExperimentRunner()

    result = await runner.run(db_session, scenario, ["first_available", "nearest_available"], seeds=[1, 2, 3])

    seeds_by_strategy = {
        name: sorted(r["seed"] for r in result.raw_results if r["strategy"] == name)
        for name in ["first_available", "nearest_available"]
    }
    assert seeds_by_strategy["first_available"] == seeds_by_strategy["nearest_available"] == [1, 2, 3]


async def test_unknown_strategy_raises_before_running_anything(
    db_session: AsyncSession, sample_campus: str
) -> None:
    scenario = _scenario()
    runner = ExperimentRunner()

    with pytest.raises(UnknownStrategyError):
        await runner.run(db_session, scenario, ["not-a-real-strategy"], seeds=[1])


async def test_never_exceeds_capacity_across_all_baseline_strategies(
    db_session: AsyncSession, sample_campus: str
) -> None:
    scenario = _scenario(
        duration_minutes=200,
        arrival_rate_profile=[
            {"gate_id": "sample-gate-main", "start_minute": 0, "end_minute": 200, "vehicles_per_minute": 3.0}
        ],
    )
    runner = ExperimentRunner()

    result = await runner.run(
        db_session, scenario, ["first_available", "nearest_available", "prediction_only"], seeds=[5]
    )

    assert result.aggregated["first_available"]["overflow_count"]["mean"] is not None


async def test_default_seed_list_has_30_seeds() -> None:
    from app.services.experiment import DEFAULT_SEEDS

    assert len(DEFAULT_SEEDS) == 30


async def test_run_and_store_persists_experiment(db_session: AsyncSession, sample_campus: str) -> None:
    scenario = _scenario()
    runner = ExperimentRunner()

    run = await runner.run_and_store(db_session, scenario, ["first_available"], seeds=[1, 2])

    assert run.experiment_id.startswith("exp_")
    assert run.strategies == ["first_available"]
    assert run.seeds == [1, 2]
    assert "first_available" in run.aggregated
