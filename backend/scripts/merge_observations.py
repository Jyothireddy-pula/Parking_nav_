"""Merge multiple observers' field survey CSV sheets into a consolidated
ingestion format (Module 2 -> Module 4).

Rows for the same (collection_session, site_id) are grouped. If every
observer's row in a group agrees on the observed values, they collapse
into one consensus row listing all contributing observers. If they
disagree, the group is a conflict: every raw row involved is written to a
separate conflicts report and none of them is written to the consolidated
output. This script never averages, picks a "majority," or otherwise
silently resolves a disagreement — a human reviews conflicts and decides.

Usage:
    python -m scripts.merge_observations parking \\
        --input observer_a.csv observer_b.csv \\
        --consolidated consolidated_parking.csv \\
        --conflicts conflicts_parking.csv
"""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

PARKING_KEY_FIELDS = ("collection_session", "parking_lot_id")
PARKING_VALUE_FIELDS = ("capacity", "occupied_spaces")

GATES_KEY_FIELDS = ("collection_session", "gate_id")
GATES_VALUE_FIELDS = ("entered", "exited")

KIND_CONFIG = {
    "parking": {"key_fields": PARKING_KEY_FIELDS, "value_fields": PARKING_VALUE_FIELDS},
    "gates": {"key_fields": GATES_KEY_FIELDS, "value_fields": GATES_VALUE_FIELDS},
}


def _read_rows(paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                row["_source_file"] = path.name
                rows.append(row)
    return rows


def merge_observations(kind: str, rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Returns (consolidated_rows, conflict_rows). consolidated_rows have one
    row per (session, site) group where every observer agreed; conflict_rows
    contains every raw row belonging to a group where observers disagreed."""

    if kind not in KIND_CONFIG:
        raise ValueError(f"unknown kind {kind!r}, expected one of {sorted(KIND_CONFIG)}")
    key_fields = KIND_CONFIG[kind]["key_fields"]
    value_fields = KIND_CONFIG[kind]["value_fields"]

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = tuple(row.get(field, "") for field in key_fields)
        groups[key].append(row)

    consolidated: list[dict] = []
    conflicts: list[dict] = []

    for key, group_rows in groups.items():
        observed_value_sets = {tuple(row.get(field, "") for field in value_fields) for row in group_rows}
        observers = sorted({row.get("observer", "") for row in group_rows})

        if len(observed_value_sets) == 1:
            consensus_values = next(iter(observed_value_sets))
            consensus_row = dict(zip(key_fields, key, strict=True))
            consensus_row.update(dict(zip(value_fields, consensus_values, strict=True)))
            consensus_row["contributing_observers"] = ";".join(observers)
            consensus_row["observation_count"] = str(len(group_rows))
            consensus_row["source_label"] = "REAL"
            consolidated.append(consensus_row)
        else:
            for row in group_rows:
                conflict_row = dict(row)
                conflict_row["conflict_reason"] = (
                    f"observers disagree on {', '.join(value_fields)} for this session/site"
                )
                conflicts.append(conflict_row)

    return consolidated, conflicts


def _write_csv(rows: list[dict], fieldnames: list[str], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("kind", choices=sorted(KIND_CONFIG))
    parser.add_argument("--input", nargs="+", required=True, type=Path)
    parser.add_argument("--consolidated", required=True, type=Path)
    parser.add_argument("--conflicts", required=True, type=Path)
    args = parser.parse_args()

    rows = _read_rows(args.input)
    consolidated, conflicts = merge_observations(args.kind, rows)

    key_fields = list(KIND_CONFIG[args.kind]["key_fields"])
    value_fields = list(KIND_CONFIG[args.kind]["value_fields"])
    consolidated_fieldnames = key_fields + value_fields + [
        "contributing_observers",
        "observation_count",
        "source_label",
    ]
    _write_csv(consolidated, consolidated_fieldnames, args.consolidated)

    if conflicts:
        conflict_fieldnames = sorted({field for row in conflicts for field in row})
        _write_csv(conflicts, conflict_fieldnames, args.conflicts)
        print(
            f"[WARN] {len(conflicts)} row(s) across "
            f"{len({tuple(row.get(f, '') for f in key_fields) for row in conflicts})} "
            f"session/site group(s) disagree and need human review: {args.conflicts}",
            file=sys.stderr,
        )
    else:
        print("[OK] no conflicts found")

    print(f"[OK] wrote {len(consolidated)} consensus row(s) to {args.consolidated}")


if __name__ == "__main__":
    main()
