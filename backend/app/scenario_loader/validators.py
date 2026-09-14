from app.scenario_loader.schema import ScenarioConfig


def validate_scenario(
    scenario: ScenarioConfig, gate_ids: set[str], parking_lot_ids: set[str], road_ids: set[str]
) -> list[str]:
    """Cross-entity checks against the real campus config: every gate_id/
    parking_lot_id/road_id a scenario references must actually exist.
    Returns every error found, not just the first."""

    errors: list[str] = []

    for entry in scenario.arrival_rate_profile:
        if entry.gate_id not in gate_ids:
            errors.append(f"arrival_rate_profile references unknown gate_id {entry.gate_id!r}")
        if entry.end_minute > scenario.duration_minutes:
            errors.append(
                f"arrival_rate_profile entry for gate {entry.gate_id!r} ends at minute "
                f"{entry.end_minute}, after scenario duration_minutes={scenario.duration_minutes}"
            )

    for override in scenario.availability_overrides:
        valid_ids = {"gate": gate_ids, "parking_lot": parking_lot_ids, "road": road_ids}[override.entity_type]
        if override.entity_id not in valid_ids:
            errors.append(
                f"availability_override references unknown {override.entity_type} {override.entity_id!r}"
            )
        if override.end_minute > scenario.duration_minutes:
            errors.append(
                f"availability_override for {override.entity_type} {override.entity_id!r} ends at minute "
                f"{override.end_minute}, after scenario duration_minutes={scenario.duration_minutes}"
            )

    for override in scenario.capacity_overrides:
        if override.parking_lot_id not in parking_lot_ids:
            errors.append(f"capacity_override references unknown parking_lot_id {override.parking_lot_id!r}")

    for event in scenario.event_conditions:
        if event.end_minute > scenario.duration_minutes:
            errors.append(
                f"event_condition {event.name!r} ends at minute {event.end_minute}, "
                f"after scenario duration_minutes={scenario.duration_minutes}"
            )

    return errors
