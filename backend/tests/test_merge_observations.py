import pytest

from scripts.merge_observations import merge_observations


def _row(**fields) -> dict:
    return dict(fields)


def test_agreeing_observers_produce_one_consensus_row() -> None:
    rows = [
        _row(
            collection_session="s1",
            parking_lot_id="lot-1",
            observer="Alice",
            capacity="100",
            occupied_spaces="42",
        ),
        _row(
            collection_session="s1",
            parking_lot_id="lot-1",
            observer="Bob",
            capacity="100",
            occupied_spaces="42",
        ),
    ]

    consolidated, conflicts = merge_observations("parking", rows)

    assert conflicts == []
    assert len(consolidated) == 1
    row = consolidated[0]
    assert row["collection_session"] == "s1"
    assert row["parking_lot_id"] == "lot-1"
    assert row["capacity"] == "100"
    assert row["occupied_spaces"] == "42"
    assert row["source_label"] == "REAL"
    assert row["observation_count"] == "2"
    assert set(row["contributing_observers"].split(";")) == {"Alice", "Bob"}


def test_disagreeing_observers_are_flagged_as_a_conflict_not_resolved() -> None:
    rows = [
        _row(
            collection_session="s1",
            parking_lot_id="lot-1",
            observer="Alice",
            capacity="100",
            occupied_spaces="42",
        ),
        _row(
            collection_session="s1",
            parking_lot_id="lot-1",
            observer="Bob",
            capacity="100",
            occupied_spaces="47",
        ),
    ]

    consolidated, conflicts = merge_observations("parking", rows)

    assert consolidated == []
    assert len(conflicts) == 2
    assert {row["observer"] for row in conflicts} == {"Alice", "Bob"}
    assert all("disagree" in row["conflict_reason"] for row in conflicts)


def test_three_observer_sheets_with_one_disagreement_isolates_only_that_group() -> None:
    rows = [
        # lot-1, session s1: all three agree.
        _row(collection_session="s1", parking_lot_id="lot-1", observer="Alice", capacity="100", occupied_spaces="10"),
        _row(collection_session="s1", parking_lot_id="lot-1", observer="Bob", capacity="100", occupied_spaces="10"),
        _row(collection_session="s1", parking_lot_id="lot-1", observer="Carol", capacity="100", occupied_spaces="10"),
        # lot-2, session s1: Alice and Bob disagree.
        _row(collection_session="s1", parking_lot_id="lot-2", observer="Alice", capacity="50", occupied_spaces="20"),
        _row(collection_session="s1", parking_lot_id="lot-2", observer="Bob", capacity="50", occupied_spaces="25"),
    ]

    consolidated, conflicts = merge_observations("parking", rows)

    assert len(consolidated) == 1
    assert consolidated[0]["parking_lot_id"] == "lot-1"
    assert len(conflicts) == 2
    assert {row["parking_lot_id"] for row in conflicts} == {"lot-2"}


def test_gates_kind_merges_on_entered_and_exited() -> None:
    rows = [
        _row(collection_session="s1", gate_id="gate-1", observer="Alice", entered="5", exited="2"),
        _row(collection_session="s1", gate_id="gate-1", observer="Bob", entered="5", exited="2"),
    ]

    consolidated, conflicts = merge_observations("gates", rows)

    assert conflicts == []
    assert len(consolidated) == 1
    assert consolidated[0]["entered"] == "5"
    assert consolidated[0]["exited"] == "2"


def test_timestamp_is_passed_through_to_the_consolidated_row() -> None:
    rows = [
        _row(
            collection_session="s1",
            parking_lot_id="lot-1",
            observer="Alice",
            capacity="100",
            occupied_spaces="42",
            timestamp="2026-01-12T09:00:00+05:30",
        ),
        _row(
            collection_session="s1",
            parking_lot_id="lot-1",
            observer="Bob",
            capacity="100",
            occupied_spaces="42",
            timestamp="2026-01-12T09:00:00+05:30",
        ),
    ]

    consolidated, _conflicts = merge_observations("parking", rows)

    assert consolidated[0]["timestamp"] == "2026-01-12T09:00:00+05:30"


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown kind"):
        merge_observations("unknown", [])
