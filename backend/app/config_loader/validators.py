from collections import Counter

from app.config_loader.schema import CampusConfigFile


def _duplicates(ids: list[str]) -> list[str]:
    counts = Counter(ids)
    return sorted(id_ for id_, count in counts.items() if count > 1)


def validate_campus_config(config: CampusConfigFile) -> list[str]:
    """Cross-entity checks that a single pydantic model cannot express on its
    own: duplicate IDs, dangling road/route references, and orphan nodes that
    never enter the routable graph. Returns every error found, not just the
    first."""

    errors: list[str] = []

    entity_lists: dict[str, list[str]] = {
        "gates": [g.gate_id for g in config.gates],
        "roads": [r.road_id for r in config.roads],
        "parking_lots": [p.parking_lot_id for p in config.parking_lots],
        "destinations": [d.destination_id for d in config.destinations],
        "events": [e.event_id for e in config.events],
    }
    for entity_name, ids in entity_lists.items():
        for dup in _duplicates(ids):
            errors.append(f"duplicate {entity_name[:-1]}_id {dup!r} in campus {config.campus_id!r}")

    # Node ids (gates, parking lots, destinations) must be unique across all
    # three types, since roads reference them by a single unnamespaced id.
    node_ids = (
        [g.gate_id for g in config.gates]
        + [p.parking_lot_id for p in config.parking_lots]
        + [d.destination_id for d in config.destinations]
    )
    for dup in _duplicates(node_ids):
        errors.append(f"node id {dup!r} is reused across gates/parking_lots/destinations in campus {config.campus_id!r}")

    node_id_set = set(node_ids)
    connected_nodes: set[str] = set()
    for road in config.roads:
        if road.start_node not in node_id_set:
            errors.append(
                f"road {road.road_id!r} start_node {road.start_node!r} does not reference "
                f"an existing gate, parking_lot, or destination"
            )
        else:
            connected_nodes.add(road.start_node)
        if road.end_node not in node_id_set:
            errors.append(
                f"road {road.road_id!r} end_node {road.end_node!r} does not reference "
                f"an existing gate, parking_lot, or destination"
            )
        else:
            connected_nodes.add(road.end_node)

    orphans = sorted(node_id_set - connected_nodes)
    for orphan in orphans:
        errors.append(f"node {orphan!r} is not connected to any road and is orphaned from the routable graph")

    for destination in config.destinations:
        for gate_id in destination.nearest_gates:
            if gate_id not in {g.gate_id for g in config.gates}:
                errors.append(
                    f"destination {destination.destination_id!r} nearest_gates references "
                    f"unknown gate {gate_id!r}"
                )
        for lot_id in destination.nearest_parking_lots:
            if lot_id not in {p.parking_lot_id for p in config.parking_lots}:
                errors.append(
                    f"destination {destination.destination_id!r} nearest_parking_lots references "
                    f"unknown parking_lot {lot_id!r}"
                )

    return errors
