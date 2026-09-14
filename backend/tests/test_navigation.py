import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_loader.schema import CampusConfigFile
from app.config_loader.upsert import upsert_campus_config
from app.models.twin import RoadState
from app.services.campus_config import CampusNotFoundError
from app.services.navigation import (
    NavigationService,
    NodeNotFoundError,
    NoFeasibleRouteError,
)

CURVED_GEOMETRY = [
    {"lat": 0.0100, "lng": 0.0000},
    {"lat": 0.0120, "lng": 0.0050},
    {"lat": 0.0150, "lng": 0.0030},
    {"lat": 0.0180, "lng": 0.0080},
    {"lat": 0.0200, "lng": 0.0000},
]

NAV_TEST_CONFIG: dict = {
    "campus_id": "navtest",
    "name": "Navigation Test Campus",
    "timezone": "Asia/Kolkata",
    "gates": [
        {
            "gate_id": "nav-gate",
            "name": "Nav Gate",
            "coordinates": {"lat": 0.0, "lng": 0.0},
            "capacity": 10,
            "status": "open",
            "provenance": "SAMPLE",
        },
    ],
    "parking_lots": [
        {
            "parking_lot_id": "nav-lot",
            "name": "Nav Lot",
            "status": "open",
            "total_capacity": 20,
            "usable_capacity": 20,
            "reserved_capacity": 0,
            "restricted_capacity": 0,
            "temporarily_unavailable_capacity": 0,
            "provenance": "SAMPLE",
        },
    ],
    "destinations": [
        {
            "destination_id": "nav-dest-near",
            "name": "Nearby Hall",
            "category": "academic_block",
            "coordinates": {"lat": 0.02, "lng": 0.0},
            "provenance": "SAMPLE",
        },
        {
            "destination_id": "nav-dest-via",
            "name": "Waypoint Block",
            "category": "administrative_building",
            "coordinates": {"lat": 0.005, "lng": 0.01},
            "provenance": "SAMPLE",
        },
        {
            "destination_id": "nav-dest-drive-only",
            "name": "Drive Only Block",
            "category": "other",
            "coordinates": {"lat": 0.03, "lng": -0.01},
            "provenance": "SAMPLE",
        },
    ],
    "roads": [
        {
            "road_id": "nav-road-gate-lot",
            "name": "Gate to Lot (direct, short)",
            "start_node": "nav-gate",
            "end_node": "nav-lot",
            "length": 10.0,
            "expected_travel_time": 8.0,
            "is_walkable": True,
            "is_driveable": True,
            "status": "open",
            "provenance": "SAMPLE",
            "geometry": [
                {"lat": 0.0, "lng": 0.0},
                {"lat": 0.005, "lng": 0.0},
                {"lat": 0.01, "lng": 0.0},
            ],
        },
        {
            "road_id": "nav-road-lot-near",
            "name": "Lot to Nearby Hall (curved)",
            "start_node": "nav-lot",
            "end_node": "nav-dest-near",
            "length": 50.0,
            "expected_travel_time": 40.0,
            "is_walkable": True,
            "is_driveable": False,
            "status": "open",
            "provenance": "SAMPLE",
            "geometry": CURVED_GEOMETRY,
        },
        {
            "road_id": "nav-road-gate-via",
            "name": "Gate to Waypoint",
            "start_node": "nav-gate",
            "end_node": "nav-dest-via",
            "length": 100.0,
            "expected_travel_time": 80.0,
            "is_walkable": True,
            "is_driveable": True,
            "status": "open",
            "provenance": "SAMPLE",
            "geometry": [
                {"lat": 0.0, "lng": 0.0},
                {"lat": 0.0025, "lng": 0.005},
                {"lat": 0.005, "lng": 0.01},
            ],
        },
        {
            "road_id": "nav-road-via-lot",
            "name": "Waypoint to Lot",
            "start_node": "nav-dest-via",
            "end_node": "nav-lot",
            "length": 100.0,
            "expected_travel_time": 80.0,
            "is_walkable": True,
            "is_driveable": True,
            "status": "open",
            "provenance": "SAMPLE",
            "geometry": [
                {"lat": 0.005, "lng": 0.01},
                {"lat": 0.0075, "lng": 0.005},
                {"lat": 0.01, "lng": 0.0},
            ],
        },
        {
            "road_id": "nav-road-lot-driveonly",
            "name": "Lot to Drive Only Block",
            "start_node": "nav-lot",
            "end_node": "nav-dest-drive-only",
            "length": 200.0,
            "expected_travel_time": 150.0,
            "is_walkable": False,
            "is_driveable": True,
            "status": "open",
            "provenance": "SAMPLE",
            "geometry": [
                {"lat": 0.01, "lng": 0.0},
                {"lat": 0.02, "lng": -0.005},
                {"lat": 0.03, "lng": -0.01},
            ],
        },
    ],
    "events": [],
}


@pytest.fixture
def service() -> NavigationService:
    return NavigationService()


@pytest.fixture
async def navtest_campus(db_session: AsyncSession) -> str:
    config = CampusConfigFile.model_validate(NAV_TEST_CONFIG)
    await upsert_campus_config(db_session, config)
    return config.campus_id


async def test_find_route_shortest_path_is_correct(
    db_session: AsyncSession, service: NavigationService, navtest_campus: str
) -> None:
    route = await service.find_route(db_session, navtest_campus, "nav-gate", "nav-lot", "walk")

    assert route.start_node_id == "nav-gate"
    assert route.end_node_id == "nav-lot"
    assert route.distance_m == pytest.approx(10.0)
    assert route.travel_time_s == pytest.approx(8.0)
    assert len(route.steps) == 1


async def test_route_polyline_matches_real_curved_road_geometry_not_a_straight_line(
    db_session: AsyncSession, service: NavigationService, navtest_campus: str
) -> None:
    route = await service.find_route(db_session, navtest_campus, "nav-lot", "nav-dest-near", "walk")

    assert route.geometry == CURVED_GEOMETRY
    # A straight line would only ever have 2 distinct points; this route's
    # concatenated geometry preserves every real intermediate point.
    assert len(route.geometry) == 5


async def test_multi_leg_route_concatenates_geometry_without_duplicating_shared_points(
    db_session: AsyncSession, service: NavigationService, navtest_campus: str
) -> None:
    route = await service.find_route(db_session, navtest_campus, "nav-gate", "nav-dest-via", "walk")

    # nav-road-gate-via alone has 3 points; a single-leg route to its own
    # endpoint should reproduce them exactly (no duplication, no loss).
    assert route.geometry == [
        {"lat": 0.0, "lng": 0.0},
        {"lat": 0.0025, "lng": 0.005},
        {"lat": 0.005, "lng": 0.01},
    ]


async def test_closed_road_is_avoided_in_favor_of_a_longer_alternate(
    db_session: AsyncSession, service: NavigationService, navtest_campus: str
) -> None:
    direct_route = await service.find_route(db_session, navtest_campus, "nav-gate", "nav-lot", "drive")
    assert direct_route.distance_m == pytest.approx(10.0)

    db_session.add(
        RoadState(road_id="nav-road-gate-lot", campus_id=navtest_campus, status="closed")
    )
    await db_session.commit()

    rerouted = await service.find_route(db_session, navtest_campus, "nav-gate", "nav-lot", "drive")

    assert rerouted.distance_m == pytest.approx(200.0)  # via nav-dest-via, the long way round
    assert "nav-dest-via" not in (rerouted.start_node_id, rerouted.end_node_id)


async def test_closed_road_with_no_alternate_raises_no_feasible_route(
    db_session: AsyncSession, service: NavigationService, navtest_campus: str
) -> None:
    db_session.add(
        RoadState(road_id="nav-road-lot-near", campus_id=navtest_campus, status="closed")
    )
    await db_session.commit()

    with pytest.raises(NoFeasibleRouteError):
        await service.find_route(db_session, navtest_campus, "nav-lot", "nav-dest-near", "walk")


async def test_unreachable_in_requested_mode_raises_no_feasible_route(
    db_session: AsyncSession, service: NavigationService, navtest_campus: str
) -> None:
    # nav-road-lot-driveonly is drive-only; walking there is genuinely impossible.
    with pytest.raises(NoFeasibleRouteError):
        await service.find_route(db_session, navtest_campus, "nav-lot", "nav-dest-drive-only", "walk")


async def test_unreachable_in_drive_mode_works_by_driving(
    db_session: AsyncSession, service: NavigationService, navtest_campus: str
) -> None:
    route = await service.find_route(db_session, navtest_campus, "nav-lot", "nav-dest-drive-only", "drive")

    assert route.end_node_id == "nav-dest-drive-only"


async def test_unknown_start_node_raises_node_not_found(
    db_session: AsyncSession, service: NavigationService, navtest_campus: str
) -> None:
    with pytest.raises(NodeNotFoundError):
        await service.find_route(db_session, navtest_campus, "does-not-exist", "nav-lot", "walk")


async def test_unknown_campus_raises(db_session: AsyncSession, service: NavigationService) -> None:
    with pytest.raises(CampusNotFoundError):
        await service.find_route(db_session, "does-not-exist", "a", "b", "walk")


async def test_find_route_to_nearest_parking_finds_the_lot(
    db_session: AsyncSession, service: NavigationService, navtest_campus: str
) -> None:
    result = await service.find_route_to_nearest(
        db_session, navtest_campus, "nav-gate", "parking_lot", "drive", require_available=False
    )

    assert result.target.node_id == "nav-lot"
    assert result.route.end_node_id == "nav-lot"


async def test_find_route_to_nearest_parking_respects_live_availability(
    db_session: AsyncSession, service: NavigationService, navtest_campus: str
) -> None:
    from app.models.twin import ParkingState

    db_session.add(
        ParkingState(
            parking_lot_id="nav-lot",
            campus_id=navtest_campus,
            total_capacity=20,
            usable_capacity=20,
            reserved_capacity=0,
            restricted_capacity=0,
            temporarily_unavailable_capacity=0,
            occupied=20,  # completely full
            status="open",
        )
    )
    await db_session.commit()

    with pytest.raises(NoFeasibleRouteError):
        await service.find_route_to_nearest(
            db_session, navtest_campus, "nav-gate", "parking_lot", "drive", require_available=True
        )


async def test_find_route_to_nearest_parking_with_no_observation_is_not_excluded(
    db_session: AsyncSession, service: NavigationService, navtest_campus: str
) -> None:
    # No ParkingState row exists at all for nav-lot (twin never initialized/
    # observed). That's MISSING data, not "assumed full" — a lot with no
    # observation must still be a valid candidate.
    result = await service.find_route_to_nearest(
        db_session, navtest_campus, "nav-gate", "parking_lot", "drive", require_available=True
    )

    assert result.target.node_id == "nav-lot"


async def test_search_destinations_matches_name_case_insensitively(
    db_session: AsyncSession, service: NavigationService, navtest_campus: str
) -> None:
    results = await service.search_destinations(db_session, navtest_campus, "nearby")

    assert {d.destination_id for d in results} == {"nav-dest-near"}


async def test_search_destinations_filters_by_category(
    db_session: AsyncSession, service: NavigationService, navtest_campus: str
) -> None:
    results = await service.search_destinations(db_session, navtest_campus, "", category="administrative_building")

    assert {d.destination_id for d in results} == {"nav-dest-via"}


async def test_search_destinations_no_match_returns_empty(
    db_session: AsyncSession, service: NavigationService, navtest_campus: str
) -> None:
    results = await service.search_destinations(db_session, navtest_campus, "nonexistent-place-xyz")

    assert results == []
