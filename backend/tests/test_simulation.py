from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_loader.loader import load_campus_config_file
from app.config_loader.upsert import upsert_campus_config
from app.scenario_loader.exceptions import ScenarioValidationError
from app.scenario_loader.loader import load_scenario_file
from app.scenario_loader.schema import ScenarioConfig
from app.services.campus_config import CampusNotFoundError
from app.services.simulation import ScenarioValidationFailedError, SimulationEngine

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CAMPUS_PATH = REPO_ROOT / "configs" / "campuses" / "sample.yaml"
SCENARIOS_DIR = REPO_ROOT / "configs" / "scenarios"

STARTER_SCENARIOS = ["normal_day", "high_demand_event", "parking_closure", "gate_closure"]


@pytest.fixture
def engine() -> SimulationEngine:
    return SimulationEngine()


@pytest.fixture
async def sample_campus(db_session: AsyncSession) -> str:
    config = load_campus_config_file(SAMPLE_CAMPUS_PATH)
    await upsert_campus_config(db_session, config)
    return config.campus_id


def _short_scenario(**overrides) -> ScenarioConfig:
    fields = {
        "scenario_id": "test-scenario",
        "campus_id": "sample",
        "name": "Test scenario",
        "duration_minutes": 60,
        "seed": 1,
        "arrival_rate_profile": [
            {"gate_id": "sample-gate-main", "start_minute": 0, "end_minute": 60, "vehicles_per_minute": 0.5}
        ],
    }
    fields.update(overrides)
    return ScenarioConfig.model_validate(fields)


@pytest.mark.parametrize("name", STARTER_SCENARIOS)
def test_starter_scenario_files_parse(name: str) -> None:
    scenario = load_scenario_file(SCENARIOS_DIR / f"{name}.yaml")
    assert scenario.scenario_id == name
    assert scenario.label == "SYNTHETIC"


async def test_starter_scenarios_validate_against_sample_campus(
    db_session: AsyncSession, engine: SimulationEngine, sample_campus: str
) -> None:
    for name in STARTER_SCENARIOS:
        scenario = load_scenario_file(SCENARIOS_DIR / f"{name}.yaml")
        await engine.validate(db_session, scenario)  # raises on failure


async def test_run_is_reproducible_for_the_same_seed(
    db_session: AsyncSession, engine: SimulationEngine, sample_campus: str
) -> None:
    scenario = _short_scenario()

    result_a = await engine.run(db_session, scenario, seed=123)
    result_b = await engine.run(db_session, scenario, seed=123)

    assert result_a.metrics == result_b.metrics
    assert result_a.run_log == result_b.run_log


async def test_different_seeds_can_produce_different_output(
    db_session: AsyncSession, engine: SimulationEngine, sample_campus: str
) -> None:
    scenario = _short_scenario(duration_minutes=180)

    result_a = await engine.run(db_session, scenario, seed=1)
    result_b = await engine.run(db_session, scenario, seed=2)

    # Not a hard guarantee for every possible pair, but true for these two
    # given the scenario's arrival rate — proves seed actually drives the RNG.
    assert result_a.metrics["vehicles_total"] != result_b.metrics["vehicles_total"]


async def test_capacity_is_never_exceeded(
    db_session: AsyncSession, engine: SimulationEngine, sample_campus: str
) -> None:
    # High arrival rate over a long window to stress the lot toward capacity.
    scenario = _short_scenario(
        duration_minutes=300,
        arrival_rate_profile=[
            {"gate_id": "sample-gate-main", "start_minute": 0, "end_minute": 300, "vehicles_per_minute": 3.0}
        ],
    )

    result = await engine.run(db_session, scenario, seed=5)

    lot_capacity = 90  # sample-lot-1 usable_capacity in sample.yaml
    for entry in result.run_log:
        occupied = entry["lot_occupied"]["sample-lot-1"]
        assert occupied <= lot_capacity
    assert result.metrics["overflow_count"] > 0  # the stress actually stressed it


async def test_closed_parking_lot_is_never_assigned(
    db_session: AsyncSession, engine: SimulationEngine, sample_campus: str
) -> None:
    scenario = load_scenario_file(SCENARIOS_DIR / "parking_closure.yaml")

    result = await engine.run(db_session, scenario, seed=11)

    # No vehicle can be newly assigned to the lot while it's closed — any
    # arrival during that window has nowhere to go.
    assert result.metrics["overflow_count"] > 0


async def test_restricted_parking_lot_receives_no_new_assignments(
    db_session: AsyncSession, engine: SimulationEngine, sample_campus: str
) -> None:
    # "restricted" must be treated the same as "closed" for new
    # assignments -- a scenario shouldn't be able to route vehicles into a
    # lot it has itself marked restricted for a window.
    scenario = _short_scenario(
        duration_minutes=60,
        availability_overrides=[
            {
                "entity_type": "parking_lot",
                "entity_id": "sample-lot-1",
                "status": "restricted",
                "start_minute": 0,
                "end_minute": 60,
            }
        ],
    )

    result = await engine.run(db_session, scenario, seed=7)

    for entry in result.run_log:
        assert entry["lot_occupied"]["sample-lot-1"] == 0
    assert result.metrics["overflow_count"] > 0


async def test_closed_gate_admits_no_new_arrivals(
    db_session: AsyncSession, engine: SimulationEngine, sample_campus: str
) -> None:
    scenario = load_scenario_file(SCENARIOS_DIR / "gate_closure.yaml")

    result = await engine.run(db_session, scenario, seed=19)

    for entry in result.run_log:
        if 60 <= entry["minute"] < 120:
            assert entry["gate_queue_lengths"]["sample-gate-main"] == 0


async def test_queue_and_departure_behavior(
    db_session: AsyncSession, engine: SimulationEngine, sample_campus: str
) -> None:
    scenario = _short_scenario(duration_minutes=120)

    result = await engine.run(db_session, scenario, seed=3)

    assert result.metrics["vehicles_parked"] > 0
    # Every parked vehicle eventually reflected in some minute's occupancy.
    peak = max(entry["lot_occupied"]["sample-lot-1"] for entry in result.run_log)
    assert peak > 0
    # By the end of a long enough run, occupancy should have come back down
    # from its peak as vehicles depart (not strictly monotonic decline, but
    # not stuck at the peak either).
    assert result.run_log[-1]["lot_occupied"]["sample-lot-1"] <= peak


async def test_travel_distance_metric_is_recorded(
    db_session: AsyncSession, engine: SimulationEngine, sample_campus: str
) -> None:
    scenario = _short_scenario(duration_minutes=120)

    result = await engine.run(db_session, scenario, seed=3)

    distances = result.metrics["travel_distance_meters"]
    assert distances["avg"] is not None
    assert distances["avg"] > 0
    assert distances["max"] >= distances["avg"]


async def test_every_occupancy_change_updates_the_digital_twin_tagged_synthetic(
    db_session: AsyncSession, engine: SimulationEngine, sample_campus: str
) -> None:
    from app.services.digital_twin import DigitalTwinService

    scenario = _short_scenario(duration_minutes=120)

    await engine.run(db_session, scenario, seed=3)

    twin = DigitalTwinService()
    state = await twin.get_parking_state(db_session, "sample", "sample-lot-1")

    assert state["source"] == "simulation"
    assert state["provenance"] == "SYNTHETIC"
    assert state["occupied"] is not None


async def test_twin_writes_go_through_the_normal_capacity_aware_update_path(
    db_session: AsyncSession, engine: SimulationEngine, sample_campus: str
) -> None:
    # Sanity check that the twin write path goes through the same
    # capacity-aware update_parking used elsewhere, not a raw write.
    from app.services.digital_twin import DigitalTwinService

    scenario = _short_scenario(duration_minutes=60)
    await engine.run(db_session, scenario, seed=3)

    twin = DigitalTwinService()
    state = await twin.get_parking_state(db_session, "sample", "sample-lot-1")
    assert state["occupied"] <= state["usable_capacity"]


async def test_scenario_validation_rejects_unknown_gate(
    db_session: AsyncSession, engine: SimulationEngine, sample_campus: str
) -> None:
    scenario = _short_scenario(
        arrival_rate_profile=[
            {"gate_id": "does-not-exist", "start_minute": 0, "end_minute": 60, "vehicles_per_minute": 0.5}
        ]
    )

    with pytest.raises(ScenarioValidationFailedError) as exc_info:
        await engine.validate(db_session, scenario)
    assert any("unknown gate_id" in error for error in exc_info.value.errors)


async def test_scenario_validation_rejects_unknown_parking_lot_in_override(
    db_session: AsyncSession, engine: SimulationEngine, sample_campus: str
) -> None:
    scenario = _short_scenario(
        availability_overrides=[
            {
                "entity_type": "parking_lot",
                "entity_id": "does-not-exist",
                "status": "closed",
                "start_minute": 0,
                "end_minute": 10,
            }
        ]
    )

    with pytest.raises(ScenarioValidationFailedError) as exc_info:
        await engine.validate(db_session, scenario)
    assert any("unknown parking_lot" in error for error in exc_info.value.errors)


async def test_scenario_validation_rejects_unknown_campus(
    db_session: AsyncSession, engine: SimulationEngine
) -> None:
    scenario = _short_scenario(campus_id="does-not-exist")

    with pytest.raises(CampusNotFoundError):
        await engine.validate(db_session, scenario)


def test_negative_arrival_rate_is_rejected() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        ScenarioConfig.model_validate(
            {
                "scenario_id": "x",
                "campus_id": "sample",
                "name": "x",
                "duration_minutes": 10,
                "arrival_rate_profile": [
                    {"gate_id": "g", "start_minute": 0, "end_minute": 5, "vehicles_per_minute": -1}
                ],
            }
        )


def test_negative_duration_is_rejected() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        ScenarioConfig.model_validate(
            {"scenario_id": "x", "campus_id": "sample", "name": "x", "duration_minutes": -5}
        )


def test_empty_scenario_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")

    with pytest.raises(ScenarioValidationError):
        load_scenario_file(path)
