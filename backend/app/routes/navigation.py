from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.navigation import (
    DestinationSearchResultOut,
    NavNodeOut,
    NearestResultOut,
    RouteLegOut,
)
from app.services.campus_config import CampusNotFoundError
from app.services.navigation import (
    NODE_TYPE_DESTINATION,
    NODE_TYPE_PARKING_LOT,
    NavigationService,
    NodeNotFoundError,
    NoFeasibleRouteError,
)

router = APIRouter(tags=["navigation"])
navigation_service = NavigationService()


def _campus_404(campus_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"campus {campus_id!r} not found")


@router.get("/campuses/{campus_id}/navigate/route", response_model=RouteLegOut)
async def get_route(
    campus_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    start: str,
    end: str,
    mode: Annotated[str, Query(pattern="^(walk|drive)$")] = "walk",
) -> RouteLegOut:
    try:
        route = await navigation_service.find_route(session, campus_id, start, end, mode)
    except CampusNotFoundError as exc:
        raise _campus_404(campus_id) from exc
    except NodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NoFeasibleRouteError as exc:
        raise HTTPException(status_code=409, detail="no feasible route") from exc
    return RouteLegOut(**route.__dict__)


@router.get("/campuses/{campus_id}/navigate/nearest-parking", response_model=NearestResultOut)
async def get_nearest_parking(
    campus_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    start: str,
    mode: Annotated[str, Query(pattern="^(walk|drive)$")] = "drive",
    require_available: bool = True,
) -> NearestResultOut:
    try:
        result = await navigation_service.find_route_to_nearest(
            session, campus_id, start, NODE_TYPE_PARKING_LOT, mode, require_available=require_available
        )
    except CampusNotFoundError as exc:
        raise _campus_404(campus_id) from exc
    except NodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NoFeasibleRouteError as exc:
        raise HTTPException(status_code=409, detail="no feasible route") from exc
    return NearestResultOut(target=NavNodeOut(**result.target.__dict__), route=RouteLegOut(**result.route.__dict__))


@router.get("/campuses/{campus_id}/navigate/nearest-destination", response_model=NearestResultOut)
async def get_nearest_destination(
    campus_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    start: str,
    mode: Annotated[str, Query(pattern="^(walk|drive)$")] = "walk",
) -> NearestResultOut:
    try:
        result = await navigation_service.find_route_to_nearest(
            session, campus_id, start, NODE_TYPE_DESTINATION, mode
        )
    except CampusNotFoundError as exc:
        raise _campus_404(campus_id) from exc
    except NodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NoFeasibleRouteError as exc:
        raise HTTPException(status_code=409, detail="no feasible route") from exc
    return NearestResultOut(target=NavNodeOut(**result.target.__dict__), route=RouteLegOut(**result.route.__dict__))


@router.get("/campuses/{campus_id}/navigate/search", response_model=list[DestinationSearchResultOut])
async def search(
    campus_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    query: str = "",
    category: str | None = None,
) -> list[DestinationSearchResultOut]:
    try:
        destinations = await navigation_service.search_destinations(session, campus_id, query, category)
    except CampusNotFoundError as exc:
        raise _campus_404(campus_id) from exc
    return [
        DestinationSearchResultOut(
            destination_id=d.destination_id,
            name=d.name,
            category=d.category,
            latitude=d.latitude,
            longitude=d.longitude,
        )
        for d in destinations
    ]
