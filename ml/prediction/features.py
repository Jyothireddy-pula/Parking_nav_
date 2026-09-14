"""Module 9 data prep: 5-min bucketing, per-lot aggregation, and feature
engineering, over a standardized input DataFrame with columns
[lot_id, timestamp, occupied, capacity] (capacity may vary per row if a
lot's config changed; it is never inferred from occupied).

Optional input columns, used only when present (a dataset that lacks them
simply doesn't get that feature -- never silently zero-filled per row):
  gate_inflow    -- vehicles entering per bucket, from Module 4 gate counts
  event_type     -- str, campus event category active in that bucket
  event_intensity -- float, campus event demand multiplier

Every lag/rolling feature is built with pandas .shift(k), k >= 1 -- i.e.
strictly from buckets before the row it describes -- so it is available at
"as-of" time for that row by construction. FEATURE_LAG_BUCKETS records that
contract per feature so leakage.py can check it, including on purpose-built
broken features in tests.
"""

import pandas as pd

BUCKET_MINUTES = 5
BUCKET = pd.Timedelta(minutes=BUCKET_MINUTES)

# How many buckets of a gap in the raw readings we're willing to
# forward-fill (rather than leave MISSING and later drop). 3 buckets = 15
# minutes -- an explicit, documented assumption, not a measured constant.
MAX_FFILL_BUCKETS = 3

# name -> lag in buckets the feature is computed from (>=1, strictly past).
# "calendar" features describe the TARGET timestamp, not the past, and are
# always legitimately knowable in advance (you always know what hour a
# future timestamp falls in) -- they carry no lag and are exempt from the
# lag>=1 check, tracked separately in CALENDAR_FEATURES.
FEATURE_LAG_BUCKETS: dict[str, int] = {
    "occupancy_lag_1": 1,
    "occupancy_lag_3": 3,
    "occupancy_lag_6": 6,
    "demand_lag_1": 1,
    "rolling_mean_6": 1,
    "rolling_std_6": 1,
    "gate_inflow_lag_1": 1,
}
CALENDAR_FEATURES: set[str] = {"hour", "day_of_week", "event_intensity_target", "has_event_target"}


def bucket_to_5min(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (lot_id, 5-min bucket). Uses the last reading observed
    in each bucket, forward-filled across gaps up to MAX_FFILL_BUCKETS;
    longer gaps are left as genuinely MISSING rows and dropped, never
    invented."""

    if df.empty:
        return df.copy()

    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)

    frames = []
    for lot_id, group in out.groupby("lot_id"):
        group = group.sort_values("timestamp").set_index("timestamp")
        resampled = group[["occupied", "capacity"]].resample(BUCKET).last()
        resampled["occupied"] = resampled["occupied"].ffill(limit=MAX_FFILL_BUCKETS)
        resampled["capacity"] = resampled["capacity"].ffill(limit=MAX_FFILL_BUCKETS).bfill(limit=MAX_FFILL_BUCKETS)
        if "gate_inflow" in group.columns:
            resampled["gate_inflow"] = group["gate_inflow"].resample(BUCKET).sum()
        if "event_type" in group.columns:
            resampled["event_type"] = group["event_type"].resample(BUCKET).last().ffill(limit=MAX_FFILL_BUCKETS)
        if "event_intensity" in group.columns:
            resampled["event_intensity"] = (
                group["event_intensity"].resample(BUCKET).last().ffill(limit=MAX_FFILL_BUCKETS)
            )
        resampled["lot_id"] = lot_id
        frames.append(resampled.reset_index())

    bucketed = pd.concat(frames, ignore_index=True)
    return bucketed.dropna(subset=["occupied", "capacity"]).reset_index(drop=True)


def build_features(bucketed: pd.DataFrame, horizon_minutes: int, require_target: bool = True) -> pd.DataFrame:
    """Per lot, per bucket: engineered features "as of" that bucket, plus
    the target occupancy `horizon_minutes` later. Rows without enough
    history for their lag features are always dropped (never imputed).

    require_target=True (training/evaluation): rows without a target
    bucket that far ahead are also dropped -- the usual case, since a
    target-less row is useless for fitting or scoring.
    require_target=False (live serving): the most recent rows -- exactly
    the ones a real prediction request needs -- have no target yet by
    definition (it hasn't happened), so they're kept with target=NaN
    instead of being dropped."""

    if horizon_minutes % BUCKET_MINUTES != 0:
        raise ValueError(f"horizon_minutes must be a multiple of {BUCKET_MINUTES}, got {horizon_minutes}")
    horizon_buckets = horizon_minutes // BUCKET_MINUTES

    frames = []
    for lot_id, group in bucketed.groupby("lot_id"):
        group = group.sort_values("timestamp").reset_index(drop=True)
        feat = pd.DataFrame({"lot_id": lot_id, "asof_ts": group["timestamp"], "capacity": group["capacity"]})

        feat["hour"] = group["timestamp"].dt.hour
        feat["day_of_week"] = group["timestamp"].dt.dayofweek

        feat["occupancy_lag_1"] = group["occupied"].shift(1)
        feat["occupancy_lag_3"] = group["occupied"].shift(3)
        feat["occupancy_lag_6"] = group["occupied"].shift(6)
        feat["demand_lag_1"] = group["occupied"].shift(1) - group["occupied"].shift(2)
        feat["rolling_mean_6"] = group["occupied"].shift(1).rolling(window=6, min_periods=6).mean()
        feat["rolling_std_6"] = group["occupied"].shift(1).rolling(window=6, min_periods=6).std()

        if "gate_inflow" in group.columns:
            feat["gate_inflow_lag_1"] = group["gate_inflow"].shift(1)
        if "event_intensity" in group.columns:
            # The target window's own event intensity -- a scheduled campus
            # event is known in advance, so this describes target_ts, not a
            # past reading, and carries no lag.
            feat["event_intensity_target"] = group["event_intensity"].shift(-horizon_buckets)
        if "event_type" in group.columns:
            # Whether *any* event is active in the target window -- same
            # "known in advance" reasoning as event_intensity_target. Not a
            # per-category one-hot: this dataset has no fixed event-type
            # vocabulary to encode against, so this is deliberately a
            # coarse presence signal rather than inventing categories.
            feat["has_event_target"] = group["event_type"].shift(-horizon_buckets).notna().astype(float)

        feat["target_ts"] = group["timestamp"].shift(-horizon_buckets)
        feat["target"] = group["occupied"].shift(-horizon_buckets)

        frames.append(feat)

    result = pd.concat(frames, ignore_index=True)
    feature_cols = [c for c in result.columns if c in FEATURE_LAG_BUCKETS or c in CALENDAR_FEATURES]
    required = [*feature_cols, "target", "target_ts"] if require_target else feature_cols
    return result.dropna(subset=required).reset_index(drop=True)


def feature_columns(df: pd.DataFrame) -> list[str]:
    """Which engineered feature columns are actually present in this
    dataset's built features -- a dataset without gate/event data simply
    doesn't offer those features, rather than having them zero-filled."""

    return [c for c in df.columns if c in FEATURE_LAG_BUCKETS or c in CALENDAR_FEATURES]
