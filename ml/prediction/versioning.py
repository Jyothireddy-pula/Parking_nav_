"""Module 9 version tags. Every stored prediction and evaluation report
carries all four — bumped by hand whenever the corresponding code changes,
never inferred. Independent of each other: a preprocessing change doesn't
require a new model_version if the model class/hyperparameters didn't
change, and vice versa."""

import hashlib

import pandas as pd

# Bump when features.py's bucketing/feature-construction logic changes.
FEATURE_VERSION = "feat-v1"

# Bump when split.py/leakage.py's train/val/test construction changes.
PREPROCESSING_VERSION = "prep-v1"

# Bump when a model class's architecture or default hyperparameters change
# (per model family, since they train independently).
MODEL_VERSIONS = {
    "historical_average": "hist_avg-v1",
    "moving_average": "moving_avg-v1",
    "xgboost": "xgboost-v1",
}


def dataset_version(label: str, df: pd.DataFrame, timestamp_col: str = "timestamp") -> str:
    """A short, reproducible identifier for exactly which rows trained a
    model: label + row count + covered time range, hashed. Two datasets
    with the same label but different rows/time range get different
    versions -- this is not a content hash of every value, just enough to
    tell "was this the same data" apart, matching what dataset drift in
    practice looks like (new rows, corrected data, resampling)."""

    if df.empty:
        return f"{label}-empty"
    start = df[timestamp_col].min()
    end = df[timestamp_col].max()
    fingerprint = f"{label}|{len(df)}|{start.isoformat()}|{end.isoformat()}"
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:12]
    return f"{label}-{digest}"
