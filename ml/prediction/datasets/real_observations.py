"""Real VIT-AP data -- Module 4's `observations` table, source_label
REAL, collection_method manual_count or a promoted cv_auto/cv_verified
reading. This module has no direct database access (it's a separate
installable package from backend/); the caller (a backend-side script)
queries observations + each lot's current usable_capacity and passes rows
here already joined. Nothing in this file invents a row that wasn't
queried from the real database.
"""

import pandas as pd


def from_observation_rows(rows: list[dict]) -> pd.DataFrame:
    """rows: [{"parking_lot_id", "timestamp", "occupied_spaces", "capacity"}, ...]
    -- already filtered by the caller to source_label == "REAL"."""

    if not rows:
        return pd.DataFrame(columns=["lot_id", "timestamp", "occupied", "capacity"])

    return pd.DataFrame(
        {
            "lot_id": [r["parking_lot_id"] for r in rows],
            "timestamp": pd.to_datetime([r["timestamp"] for r in rows], utc=True),
            "occupied": [float(r["occupied_spaces"]) for r in rows],
            "capacity": [float(r["capacity"]) for r in rows],
        }
    )
