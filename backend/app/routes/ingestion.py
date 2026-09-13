from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.ingestion import (
    IngestionBatchResultOut,
    ObservationIn,
    ObservationOut,
    ObservationRejectedOut,
    QualityReportOut,
)
from app.services.campus_config import CampusNotFoundError
from app.services.ingestion import IngestionService

router = APIRouter(tags=["ingestion"])
ingestion_service = IngestionService()

VALID_CSV_FORMATS = ("unified", "module2_parking", "module2_gates")


def _batch_result(batch, accepted, rejected) -> IngestionBatchResultOut:
    return IngestionBatchResultOut(
        batch_id=batch.batch_id,
        campus_id=batch.campus_id,
        submitted_via=batch.submitted_via,
        total_rows=batch.total_rows,
        accepted_rows=batch.accepted_rows,
        rejected_rows=batch.rejected_rows,
        accepted=[ObservationOut.model_validate(row) for row in accepted],
        rejected=[ObservationRejectedOut.model_validate(row) for row in rejected],
    )


@router.post("/campuses/{campus_id}/observations", response_model=ObservationOut, status_code=201)
async def post_observation(
    campus_id: str,
    observation: ObservationIn,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ObservationOut:
    try:
        accepted, rejected = await ingestion_service.ingest_one(session, campus_id, observation)
    except CampusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"campus {campus_id!r} not found") from exc

    if rejected is not None:
        raise HTTPException(status_code=422, detail=rejected.reason)
    return ObservationOut.model_validate(accepted)


@router.post("/campuses/{campus_id}/observations/bulk-csv", response_model=IngestionBatchResultOut)
async def post_observations_bulk_csv(
    campus_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File()],
    csv_format: Annotated[str, Form()] = "unified",
) -> IngestionBatchResultOut:
    if csv_format not in VALID_CSV_FORMATS:
        raise HTTPException(status_code=422, detail=f"csv_format must be one of {VALID_CSV_FORMATS}")

    raw_bytes = await file.read()
    try:
        batch = await ingestion_service.ingest_bulk_csv(session, campus_id, raw_bytes.decode("utf-8"), csv_format)
    except CampusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"campus {campus_id!r} not found") from exc

    accepted = await ingestion_service.list_observations(session, campus_id, limit=batch.total_rows or 1000)
    accepted_in_batch = [row for row in accepted if row.batch_id == batch.batch_id]
    rejected_in_batch = await ingestion_service.list_rejected(session, campus_id, batch_id=batch.batch_id)
    return _batch_result(batch, accepted_in_batch, rejected_in_batch)


@router.post("/campuses/{campus_id}/observations/cv-batch", response_model=IngestionBatchResultOut)
async def post_observations_cv_batch(
    campus_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    observations: Annotated[list[ObservationIn], Body()],
) -> IngestionBatchResultOut:
    try:
        batch = await ingestion_service.ingest_cv_batch(session, campus_id, observations)
    except CampusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"campus {campus_id!r} not found") from exc

    accepted = await ingestion_service.list_observations(session, campus_id, limit=batch.total_rows or 1000)
    accepted_in_batch = [row for row in accepted if row.batch_id == batch.batch_id]
    rejected_in_batch = await ingestion_service.list_rejected(session, campus_id, batch_id=batch.batch_id)
    return _batch_result(batch, accepted_in_batch, rejected_in_batch)


@router.get("/campuses/{campus_id}/observations", response_model=list[ObservationOut])
async def get_observations(
    campus_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    gate_id: str | None = None,
    parking_lot_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[ObservationOut]:
    try:
        observations = await ingestion_service.list_observations(
            session, campus_id, gate_id=gate_id, parking_lot_id=parking_lot_id, limit=limit
        )
    except CampusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"campus {campus_id!r} not found") from exc
    return [ObservationOut.model_validate(row) for row in observations]


@router.get("/campuses/{campus_id}/observations/quality-report", response_model=QualityReportOut)
async def get_quality_report(
    campus_id: str, session: Annotated[AsyncSession, Depends(get_db)]
) -> QualityReportOut:
    try:
        report = await ingestion_service.get_quality_report(session, campus_id)
    except CampusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"campus {campus_id!r} not found") from exc
    return QualityReportOut.model_validate(report)
