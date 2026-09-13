"""Generate a printable field survey roster (Module 2).

Picks a bounded set of priority lots/gates (not the whole campus),
schedules weekday morning/midday/evening sessions across a date range plus
any explicitly given high-demand periods, assigns observers round-robin,
and marks exactly one session per priority lot as a ground-truth
double-observer session (see docs/FIELD_SURVEY.md).

Usage:
    python -m scripts.generate_schedule \\
        --lots sample-lot-1:100 sample-lot-2:60 \\
        --gates sample-gate-main:50 \\
        --team-size 4 \\
        --start-date 2026-01-12 --end-date 2026-01-16 \\
        --high-demand "2026-01-14|09:00-10:00|orientation_day" \\
        --output schedule.csv
"""

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date, timedelta

STANDARD_SLOTS: list[tuple[str, str, str]] = [
    ("morning", "08:00", "10:00"),
    ("midday", "12:00", "14:00"),
    ("evening", "17:00", "19:00"),
]

MIN_PRIORITY_LOTS = 3
MAX_PRIORITY_LOTS = 5
MIN_PRIORITY_GATES = 2
MAX_PRIORITY_GATES = 3


@dataclass(frozen=True)
class HighDemandSlot:
    on_date: date
    start: str
    end: str
    label: str


def select_priority_sites(
    sites: list[tuple[str, int]], minimum: int, maximum: int
) -> list[str]:
    """Pick the highest-capacity sites, bounded to [minimum, maximum] (or
    fewer if there simply aren't that many sites). Ranking by capacity
    concentrates survey effort where the ground-truth data matters most,
    rather than spreading a small team across the whole campus."""

    ranked = sorted(sites, key=lambda item: item[1], reverse=True)
    count = max(minimum, 1) if len(ranked) < minimum else min(maximum, len(ranked))
    count = min(count, len(ranked))
    return [site_id for site_id, _capacity in ranked[:count]]


def _date_range(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError("end_date must not be before start_date")
    days = (end - start).days
    return [start + timedelta(days=offset) for offset in range(days + 1)]


def generate_schedule(
    priority_lots: list[str],
    priority_gates: list[str],
    observer_names: list[str],
    start_date: date,
    end_date: date,
    high_demand_slots: list[HighDemandSlot] | None = None,
) -> list[dict]:
    """Build the session roster. Returns one row per (date, time slot, site).
    Exactly one session per priority lot is marked ground_truth_session=True
    with two observers assigned; every other session gets one observer,
    round-robin across observer_names."""

    if not observer_names:
        raise ValueError("at least one observer name is required")

    high_demand_slots = high_demand_slots or []
    sites: list[tuple[str, str]] = [("parking_lot", lot_id) for lot_id in priority_lots] + [
        ("gate", gate_id) for gate_id in priority_gates
    ]

    sessions: list[dict] = []
    observer_cycle_index = 0

    def next_observer() -> str:
        nonlocal observer_cycle_index
        name = observer_names[observer_cycle_index % len(observer_names)]
        observer_cycle_index += 1
        return name

    for day in _date_range(start_date, end_date):
        for slot_label, slot_start, slot_end in STANDARD_SLOTS:
            for site_type, site_id in sites:
                sessions.append(
                    {
                        "date": day.isoformat(),
                        "time_slot": slot_label,
                        "slot_start": slot_start,
                        "slot_end": slot_end,
                        "site_type": site_type,
                        "site_id": site_id,
                        "observers": [next_observer()],
                        "ground_truth_session": False,
                        "notes": "",
                    }
                )

        for high_demand in high_demand_slots:
            if high_demand.on_date != day:
                continue
            for site_type, site_id in sites:
                sessions.append(
                    {
                        "date": day.isoformat(),
                        "time_slot": "high_demand",
                        "slot_start": high_demand.start,
                        "slot_end": high_demand.end,
                        "site_type": site_type,
                        "site_id": site_id,
                        "observers": [next_observer()],
                        "ground_truth_session": False,
                        "notes": high_demand.label,
                    }
                )

    # Ground-truth rule: exactly one session per priority lot gets a second,
    # independent observer. Prefer a high-demand session for that lot (real
    # busy conditions are the more informative test of counting agreement);
    # otherwise fall back to the lot's earliest scheduled session.
    for lot_id in priority_lots:
        lot_sessions = [s for s in sessions if s["site_type"] == "parking_lot" and s["site_id"] == lot_id]
        if not lot_sessions:
            continue
        high_demand_sessions = [s for s in lot_sessions if s["time_slot"] == "high_demand"]
        chosen = high_demand_sessions[0] if high_demand_sessions else lot_sessions[0]
        chosen["ground_truth_session"] = True
        second_observer = next_observer()
        while second_observer in chosen["observers"] and len(observer_names) > 1:
            second_observer = next_observer()
        chosen["observers"].append(second_observer)

    return sessions


def _write_csv(sessions: list[dict], output_path) -> None:
    fieldnames = [
        "date",
        "time_slot",
        "slot_start",
        "slot_end",
        "site_type",
        "site_id",
        "observers",
        "ground_truth_session",
        "notes",
    ]
    with open(output_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for session in sessions:
            row = dict(session)
            row["observers"] = ";".join(session["observers"])
            row["ground_truth_session"] = "true" if session["ground_truth_session"] else "false"
            writer.writerow(row)


def _parse_capacity_pairs(raw_pairs: list[str]) -> list[tuple[str, int]]:
    pairs = []
    for raw in raw_pairs:
        site_id, separator, capacity_str = raw.partition(":")
        if not separator or not capacity_str.strip():
            raise ValueError(f"expected 'site_id:capacity', got {raw!r}")
        pairs.append((site_id, int(capacity_str)))
    return pairs


def _parse_high_demand(raw_values: list[str]) -> list[HighDemandSlot]:
    slots = []
    for raw in raw_values:
        try:
            date_str, time_range, label = raw.split("|", 2)
            start, end = time_range.split("-")
        except ValueError as exc:
            raise ValueError(f"expected 'YYYY-MM-DD|HH:MM-HH:MM|label', got {raw!r}") from exc
        slots.append(HighDemandSlot(on_date=date.fromisoformat(date_str), start=start, end=end, label=label))
    return slots


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lots", nargs="+", required=True, help="lot_id:capacity pairs, e.g. lot-1:100")
    parser.add_argument("--gates", nargs="+", required=True, help="gate_id:capacity pairs")
    parser.add_argument("--team-size", type=int, required=True)
    parser.add_argument("--observer-names", nargs="*", help="Optional explicit names; defaults to Observer 1..N")
    parser.add_argument("--start-date", required=True, type=date.fromisoformat)
    parser.add_argument("--end-date", required=True, type=date.fromisoformat)
    parser.add_argument(
        "--high-demand",
        nargs="*",
        default=[],
        help="'YYYY-MM-DD|HH:MM-HH:MM|label', e.g. '2026-01-14|09:00-10:00|orientation_day'",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if args.observer_names and len(args.observer_names) != args.team_size:
        print("[FAIL] --observer-names count must match --team-size", file=sys.stderr)
        raise SystemExit(1)
    observer_names = args.observer_names or [f"Observer {i + 1}" for i in range(args.team_size)]

    lots = _parse_capacity_pairs(args.lots)
    gates = _parse_capacity_pairs(args.gates)
    priority_lots = select_priority_sites(lots, MIN_PRIORITY_LOTS, MAX_PRIORITY_LOTS)
    priority_gates = select_priority_sites(gates, MIN_PRIORITY_GATES, MAX_PRIORITY_GATES)
    high_demand_slots = _parse_high_demand(args.high_demand)

    sessions = generate_schedule(
        priority_lots, priority_gates, observer_names, args.start_date, args.end_date, high_demand_slots
    )
    _write_csv(sessions, args.output)
    print(
        f"[OK] wrote {len(sessions)} session(s) to {args.output} "
        f"({len(priority_lots)} priority lot(s), {len(priority_gates)} priority gate(s))"
    )


if __name__ == "__main__":
    main()
