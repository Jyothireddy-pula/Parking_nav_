from datetime import date

import pytest

from scripts.generate_schedule import (
    STANDARD_SLOTS,
    HighDemandSlot,
    generate_schedule,
    select_priority_sites,
)


def test_select_priority_sites_picks_highest_capacity_within_bounds() -> None:
    lots = [(f"lot-{i}", i * 10) for i in range(1, 8)]  # 7 candidates

    chosen = select_priority_sites(lots, minimum=3, maximum=5)

    assert chosen == ["lot-7", "lot-6", "lot-5", "lot-4", "lot-3"]


def test_select_priority_sites_never_exceeds_available_sites() -> None:
    lots = [("lot-1", 10), ("lot-2", 20)]

    chosen = select_priority_sites(lots, minimum=3, maximum=5)

    assert chosen == ["lot-2", "lot-1"]


def test_generate_schedule_covers_standard_slots_across_the_date_range() -> None:
    sessions = generate_schedule(
        priority_lots=["lot-1"],
        priority_gates=["gate-1"],
        observer_names=["A", "B"],
        start_date=date(2026, 1, 12),
        end_date=date(2026, 1, 13),
    )

    dates = {s["date"] for s in sessions}
    assert dates == {"2026-01-12", "2026-01-13"}
    slots = {s["time_slot"] for s in sessions if s["time_slot"] != "high_demand"}
    assert slots == {label for label, _, _ in STANDARD_SLOTS}
    # 2 sites (1 lot + 1 gate) * 3 slots * 2 days = 12 sessions. The
    # ground-truth rule adds a second observer to an existing session rather
    # than creating a new row.
    assert len(sessions) == 2 * len(STANDARD_SLOTS) * 2


def test_high_demand_slot_only_applies_on_its_date() -> None:
    sessions = generate_schedule(
        priority_lots=["lot-1"],
        priority_gates=[],
        observer_names=["A"],
        start_date=date(2026, 1, 12),
        end_date=date(2026, 1, 13),
        high_demand_slots=[HighDemandSlot(date(2026, 1, 12), "09:00", "10:00", "orientation_day")],
    )

    high_demand_sessions = [s for s in sessions if s["time_slot"] == "high_demand"]
    assert len(high_demand_sessions) == 1
    assert high_demand_sessions[0]["date"] == "2026-01-12"
    assert high_demand_sessions[0]["notes"] == "orientation_day"


def test_every_priority_lot_gets_exactly_one_ground_truth_session() -> None:
    sessions = generate_schedule(
        priority_lots=["lot-1", "lot-2"],
        priority_gates=["gate-1"],
        observer_names=["A", "B", "C"],
        start_date=date(2026, 1, 12),
        end_date=date(2026, 1, 12),
    )

    for lot_id in ("lot-1", "lot-2"):
        lot_sessions = [s for s in sessions if s["site_type"] == "parking_lot" and s["site_id"] == lot_id]
        ground_truth = [s for s in lot_sessions if s["ground_truth_session"]]
        assert len(ground_truth) == 1
        assert len(ground_truth[0]["observers"]) == 2
        assert len(set(ground_truth[0]["observers"])) == 2

    gate_sessions = [s for s in sessions if s["site_type"] == "gate"]
    assert all(not s["ground_truth_session"] for s in gate_sessions)


def test_ground_truth_session_prefers_the_high_demand_slot() -> None:
    sessions = generate_schedule(
        priority_lots=["lot-1"],
        priority_gates=[],
        observer_names=["A", "B"],
        start_date=date(2026, 1, 12),
        end_date=date(2026, 1, 12),
        high_demand_slots=[HighDemandSlot(date(2026, 1, 12), "09:00", "10:00", "orientation_day")],
    )

    ground_truth = next(s for s in sessions if s["ground_truth_session"])
    assert ground_truth["time_slot"] == "high_demand"


def test_empty_observer_list_is_rejected() -> None:
    with pytest.raises(ValueError, match="observer"):
        generate_schedule(["lot-1"], [], [], date(2026, 1, 12), date(2026, 1, 12))


def test_end_before_start_is_rejected() -> None:
    with pytest.raises(ValueError, match="end_date"):
        generate_schedule(["lot-1"], [], ["A"], date(2026, 1, 13), date(2026, 1, 12))
