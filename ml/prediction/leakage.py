"""Automated leakage check: no feature's timestamp may be later than its
target's. Two checks, both must pass:

1. Structural: for every row, asof_ts < target_ts. Catches a
   misconfigured horizon (e.g. horizon <= 0, or a target built with the
   wrong shift direction).
2. Per-feature contract: every declared feature is either a CALENDAR
   feature (describes target_ts, always knowable in advance) or has a
   registered lag >= 1 bucket in features.FEATURE_LAG_BUCKETS -- i.e. is
   built only from buckets strictly before asof_ts. A feature with lag 0
   or missing from the registry (the shape a leaking feature actually
   takes -- "current" or unregistered data slipped in) fails this check.
"""

import pandas as pd

from prediction.features import CALENDAR_FEATURES, FEATURE_LAG_BUCKETS


class LeakageError(Exception):
    pass


def check_no_leakage(df: pd.DataFrame, feature_cols: list[str]) -> None:
    if df.empty:
        return

    if not (df["asof_ts"] < df["target_ts"]).all():
        raise LeakageError("found row(s) where asof_ts is not strictly before target_ts")

    for name in feature_cols:
        if name in CALENDAR_FEATURES:
            continue
        lag = FEATURE_LAG_BUCKETS.get(name)
        if lag is None:
            raise LeakageError(f"feature {name!r} has no registered lag and is not a calendar feature")
        if lag < 1:
            raise LeakageError(f"feature {name!r} has lag={lag} (< 1 bucket) -- uses current or future data")
