from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.campus import DestinationOut, EventOut, GateOut, ParkingLotOut, RoadOut
from app.services.campus_config import CampusConfigService, CampusNotFoundError

router = APIRouter(tags=["campus-config"])
campus_config_service = CampusConfigService()


async def _handle_not_found(campus_id: str, coro):
    try:
        return await coro
    except CampusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"campus {campus_id!r} not found") from exc


@router.get("/campuses/{campus_id}/gates", response_model=list[GateOut])
async def list_gates(campus_id: str, session: Annotated[AsyncSession, Depends(get_db)]) -> list[GateOut]:
    gates = await _handle_not_found(campus_id, campus_config_service.get_gates(session, campus_id))
    return [GateOut.model_validate(gate) for gate in gates]


@router.get("/campuses/{campus_id}/roads", response_model=list[RoadOut])
async def list_roads(campus_id: str, session: Annotated[AsyncSession, Depends(get_db)]) -> list[RoadOut]:
    roads = await _handle_not_found(campus_id, campus_config_service.get_roads(session, campus_id))
    return [RoadOut.model_validate(road) for road in roads]


@router.get("/campuses/{campus_id}/parking-lots", response_model=list[ParkingLotOut])
async def list_parking_lots(
    campus_id: str, session: Annotated[AsyncSession, Depends(get_db)]
) -> list[ParkingLotOut]:
    lots = await _handle_not_found(campus_id, campus_config_service.get_parking_lots(session, campus_id))
    return [ParkingLotOut.model_validate(lot) for lot in lots]


@router.get("/campuses/{campus_id}/destinations", response_model=list[DestinationOut])
async def list_destinations(
    campus_id: str, session: Annotated[AsyncSession, Depends(get_db)]
) -> list[DestinationOut]:
    destinations = await _handle_not_found(campus_id, campus_config_service.get_destinations(session, campus_id))
    return [DestinationOut.model_validate(destination) for destination in destinations]


@router.get("/campuses/{campus_id}/events", response_model=list[EventOut])
async def list_events(campus_id: str, session: Annotated[AsyncSession, Depends(get_db)]) -> list[EventOut]:
    events = await _handle_not_found(campus_id, campus_config_service.get_events(session, campus_id))
    return [EventOut.model_validate(event) for event in events]
