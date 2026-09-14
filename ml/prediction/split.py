"""Chronological train/validation/test split -- never a random shuffle,
which would leak future buckets into training for a time-series problem."""

import pandas as pd


def chronological_split(
    df: pd.DataFrame, train_frac: float = 0.7, val_frac: float = 0.15, timestamp_col: str = "asof_ts"
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not 0 < train_frac < 1 or not 0 < val_frac < 1 or train_frac + val_frac >= 1:
        raise ValueError("train_frac and val_frac must each be in (0, 1) and sum to < 1")

    ordered = df.sort_values(timestamp_col).reset_index(drop=True)
    n = len(ordered)
    train_end = int(n * train_frac)
    val_end = train_end + int(n * val_frac)

    train = ordered.iloc[:train_end].reset_index(drop=True)
    val = ordered.iloc[train_end:val_end].reset_index(drop=True)
    test = ordered.iloc[val_end:].reset_index(drop=True)
    return train, val, test
