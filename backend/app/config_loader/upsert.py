from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_loader.schema import CampusConfigFile
from app.models.campus import Campus
from app.models.destination import Destination
from app.models.event import Event
from app.models.gate import Gate
from app.models.parking_lot import ParkingLot
from app.models.road import Road
from app.models.route_edge import RouteEdge


async def _prune_removed(session: AsyncSession, model, campus_id: str, id_column, keep_ids: set[str]) -> None:
    stmt = delete(model).where(model.campus_id == campus_id)
    if keep_ids:
        stmt = stmt.where(id_column.not_in(keep_ids))
    await session.execute(stmt)


async def upsert_campus_config(session: AsyncSession, config: CampusConfigFile) -> int:
    """Idempotently write one validated campus config into the database.
    Re-running with the same file yields the same rows; entities removed
    from the file are pruned. Every written row is stamped with the new
    configuration_version."""

    existing = await session.get(Campus, config.campus_id)
    new_version = (existing.active_configuration_version + 1) if existing else 1

    await session.merge(
        Campus(
            campus_id=config.campus_id,
            name=config.name,
            description=config.description,
            timezone=config.timezone,
            active_configuration_version=new_version,
        )
    )

    await _prune_removed(
        session, Gate, config.campus_id, Gate.gate_id, {g.gate_id for g in config.gates}
    )
    for gate in config.gates:
        await session.merge(
            Gate(
                gate_id=gate.gate_id,
                campus_id=config.campus_id,
                name=gate.name,
                latitude=gate.coordinates.lat,
                longitude=gate.coordinates.lng,
                capacity=gate.capacity,
                status=gate.status,
                configuration_version=new_version,
            )
        )

    await _prune_removed(
        session, ParkingLot, config.campus_id, ParkingLot.parking_lot_id,
        {p.parking_lot_id for p in config.parking_lots},
    )
    for lot in config.parking_lots:
        await session.merge(
            ParkingLot(
                parking_lot_id=lot.parking_lot_id,
                campus_id=config.campus_id,
                name=lot.name,
                status=lot.status,
                camera_available=lot.camera_available,
                camera_notes=lot.camera_notes,
                center_latitude=lot.center.lat if lot.center else None,
                center_longitude=lot.center.lng if lot.center else None,
                geometry=[point.model_dump() for point in lot.geometry] if lot.geometry else None,
                total_capacity=lot.total_capacity,
                usable_capacity=lot.usable_capacity,
                reserved_capacity=lot.reserved_capacity,
                restricted_capacity=lot.restricted_capacity,
                temporarily_unavailable_capacity=lot.temporarily_unavailable_capacity,
                configuration_version=new_version,
            )
        )

    await _prune_removed(
        session, Destination, config.campus_id, Destination.destination_id,
        {d.destination_id for d in config.destinations},
    )
    for destination in config.destinations:
        await session.merge(
            Destination(
                destination_id=destination.destination_id,
                campus_id=config.campus_id,
                name=destination.name,
                category=destination.category,
                latitude=destination.coordinates.lat,
                longitude=destination.coordinates.lng,
                department_names=list(destination.department_names),
                searchable_aliases=list(destination.searchable_aliases),
                nearest_gates=list(destination.nearest_gates),
                nearest_parking_lots=list(destination.nearest_parking_lots),
                configuration_version=new_version,
            )
        )

    await _prune_removed(
        session, Event, config.campus_id, Event.event_id, {e.event_id for e in config.events}
    )
    for event in config.events:
        await session.merge(
            Event(
                event_id=event.event_id,
                campus_id=config.campus_id,
                event_type=event.event_type,
                name=event.name,
                start_time=event.start_time,
                end_time=event.end_time,
                expected_demand_multiplier=event.expected_demand_multiplier,
                affected_zones=list(event.affected_zones),
                status=event.status,
                configuration_version=new_version,
            )
        )

    await _prune_removed(
        session, Road, config.campus_id, Road.road_id, {r.road_id for r in config.roads}
    )
    for road in config.roads:
        await session.merge(
            Road(
                road_id=road.road_id,
                campus_id=config.campus_id,
                name=road.name,
                start_node=road.start_node,
                end_node=road.end_node,
                length=road.length,
                expected_travel_time=road.expected_travel_time,
                is_walkable=road.is_walkable,
                is_driveable=road.is_driveable,
                status=road.status,
                geometry=[point.model_dump() for point in road.geometry],
                configuration_version=new_version,
            )
        )

    # Route edges are entirely derived from roads, so regenerate them fresh
    # on every load rather than trying to prune/merge individually.
    await session.execute(delete(RouteEdge).where(RouteEdge.campus_id == config.campus_id))
    for road in config.roads:
        modes = []
        if road.is_walkable:
            modes.append("walk")
        if road.is_driveable:
            modes.append("drive")
        for mode in modes:
            await session.merge(
                RouteEdge(
                    route_edge_id=f"{road.road_id}:{mode}:forward",
                    campus_id=config.campus_id,
                    road_id=road.road_id,
                    from_node=road.start_node,
                    to_node=road.end_node,
                    mode=mode,
                    distance=road.length,
                    travel_time=road.expected_travel_time,
                    configuration_version=new_version,
                )
            )
            await session.merge(
                RouteEdge(
                    route_edge_id=f"{road.road_id}:{mode}:reverse",
                    campus_id=config.campus_id,
                    road_id=road.road_id,
                    from_node=road.end_node,
                    to_node=road.start_node,
                    mode=mode,
                    distance=road.length,
                    travel_time=road.expected_travel_time,
                    configuration_version=new_version,
                )
            )

    await session.commit()
    return new_version
