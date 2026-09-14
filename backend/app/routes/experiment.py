import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.experiment import ExperimentRun
from app.scenario_loader.exceptions import ScenarioValidationError
from app.scenario_loader.schema import ScenarioConfig
from app.schemas.experiment import (
    ExperimentCompareOut,
    ExperimentCreateRequest,
    ExperimentOut,
)
from app.services.allocation import UnknownStrategyError
from app.services.campus_config import CampusNotFoundError
from app.services.experiment import ExperimentRunner, compare_by_metric, get_experiment
from app.services.simulation import ScenarioValidationFailedError

router = APIRouter(tags=["experiments"])
runner = ExperimentRunner()


def _experiment_404(experiment_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"experiment {experiment_id!r} not found")


def _to_out(run: ExperimentRun) -> ExperimentOut:
    return ExperimentOut(
        experiment_id=run.experiment_id,
        campus_id=run.campus_id,
        scenario_id=run.scenario_id,
        strategies=run.strategies,
        seeds=run.seeds,
        started_at=run.started_at,
        finished_at=run.finished_at,
        raw_results=run.raw_results,
        aggregated=run.aggregated,
    )


@router.post("/experiments", response_model=ExperimentOut, status_code=201)
async def create_experiment(
    request: ExperimentCreateRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ExperimentOut:
    try:
        scenario = ScenarioConfig.model_validate(request.scenario)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    try:
        run = await runner.run_and_store(session, scenario, request.strategies, request.seeds)
    except CampusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"campus {scenario.campus_id!r} not found") from exc
    except (ScenarioValidationFailedError, ScenarioValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except UnknownStrategyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _to_out(run)


@router.get("/experiments/{experiment_id}", response_model=ExperimentOut)
async def read_experiment(
    experiment_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ExperimentOut:
    run = await get_experiment(session, experiment_id)
    if run is None:
        raise _experiment_404(experiment_id)
    return _to_out(run)


@router.get("/experiments/{experiment_id}/compare", response_model=ExperimentCompareOut)
async def compare_experiment(
    experiment_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ExperimentCompareOut:
    run = await get_experiment(session, experiment_id)
    if run is None:
        raise _experiment_404(experiment_id)
    return ExperimentCompareOut(experiment_id=run.experiment_id, by_metric=compare_by_metric(run.aggregated))


@router.get("/experiments/{experiment_id}/export")
async def export_experiment(
    experiment_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PlainTextResponse:
    """Every raw (strategy, seed) run as CSV — the same numbers behind the
    stored aggregates, for external analysis. Never a separately edited copy."""

    run = await get_experiment(session, experiment_id)
    if run is None:
        raise _experiment_404(experiment_id)

    metric_keys = sorted({key for entry in run.raw_results for key in entry["metrics"]})
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["strategy", "seed", "run_id", *metric_keys])
    for entry in run.raw_results:
        writer.writerow(
            [entry["strategy"], entry["seed"], entry["run_id"]]
            + [entry["metrics"].get(key) for key in metric_keys]
        )

    return PlainTextResponse(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{experiment_id}.csv"'},
    )
