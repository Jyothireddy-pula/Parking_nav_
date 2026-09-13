from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.twin import ParkingStateOut, TwinSnapshotOut, TwinStateOut
from app.services.campus_config import CampusNotFoundError
from app.services.digital_twin import DigitalTwinService, EntityNotFoundError

router = APIRouter(tags=["digital-twin"])
digital_twin_service = DigitalTwinService()


@router.get("/campuses/{campus_id}/state", response_model=TwinStateOut)
async def get_state(campus_id: str, session: Annotated[AsyncSession, Depends(get_db)]) -> TwinStateOut:
    try:
        state = await digital_twin_service.get_state(session, campus_id)
    except CampusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"campus {campus_id!r} not found") from exc
    return TwinStateOut.model_validate(state)


@router.get("/campuses/{campus_id}/state/parking/{lot_id}", response_model=ParkingStateOut)
async def get_parking_state(
    campus_id: str, lot_id: str, session: Annotated[AsyncSession, Depends(get_db)]
) -> ParkingStateOut:
    try:
        state = await digital_twin_service.get_parking_state(session, campus_id, lot_id)
    except CampusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"campus {campus_id!r} not found") from exc
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ParkingStateOut.model_validate(state)


@router.get("/campuses/{campus_id}/state/history", response_model=list[TwinSnapshotOut])
async def get_state_history(
    campus_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[TwinSnapshotOut]:
    try:
        snapshots = await digital_twin_service.get_history(session, campus_id, limit)
    except CampusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"campus {campus_id!r} not found") from exc
    return [TwinSnapshotOut.model_validate(snapshot) for snapshot in snapshots]
