"""B1 baseline: predicts a lot's historical mean occupancy for the same
(hour, day_of_week) bucket. No trend, no recent-state awareness -- the
floor every richer model should beat."""

import json
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

MODEL_VERSION = "hist_avg-v1"


class HistoricalAverageModel:
    def __init__(self) -> None:
        self._by_group: dict[tuple, tuple[float, float]] = {}
        self._by_lot: dict[str, tuple[float, float]] = {}
        self._global: tuple[float, float] | None = None
        self._fitted = False

    def fit(self, train_df: pd.DataFrame, feature_cols: list[str], target_col: str = "target") -> None:
        self._by_group = {
            key: (float(group[target_col].mean()), float(group[target_col].std(ddof=0)) or 0.0)
            for key, group in train_df.groupby(["lot_id", "hour", "day_of_week"])
        }
        self._by_lot = {
            lot_id: (float(group[target_col].mean()), float(group[target_col].std(ddof=0)) or 0.0)
            for lot_id, group in train_df.groupby("lot_id")
        }
        self._global = (float(train_df[target_col].mean()), float(train_df[target_col].std(ddof=0)) or 0.0)
        self._fitted = True

    def _lookup(self, row: pd.Series) -> tuple[float, float]:
        key = (row["lot_id"], int(row["hour"]), int(row["day_of_week"]))
        if key in self._by_group:
            return self._by_group[key]
        if row["lot_id"] in self._by_lot:
            return self._by_lot[row["lot_id"]]
        return self._global

    def predict(self, df: pd.DataFrame, feature_cols: list[str]) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("model has not been fitted or loaded")
        return np.array([self._lookup(row)[0] for _, row in df.iterrows()])

    def predict_interval(
        self, df: pd.DataFrame, feature_cols: list[str], lower_q: float = 0.1, upper_q: float = 0.9
    ) -> tuple[np.ndarray, np.ndarray]:
        # Normal approximation from the group's own historical spread --
        # not a measured quantile of the residual distribution, an
        # explicit, documented assumption.
        z_lo, z_hi = NormalDist().inv_cdf(lower_q), NormalDist().inv_cdf(upper_q)
        point = self.predict(df, feature_cols)
        stds = np.array([self._lookup(row)[1] for _, row in df.iterrows()])
        return point + z_lo * stds, point + z_hi * stds

    def save(self, path: str) -> None:
        if not self._fitted:
            raise RuntimeError("refusing to save an unfitted model")
        payload = {
            "by_group": {"|".join(map(str, k)): v for k, v in self._by_group.items()},
            "by_lot": self._by_lot,
            "global": self._global,
        }
        Path(path).write_text(json.dumps(payload), encoding="utf-8")

    @classmethod
    def load(cls, path: str) -> "HistoricalAverageModel":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        model = cls()
        model._by_group = {}
        for key, value in payload["by_group"].items():
            lot_id, hour, dow = key.split("|")
            model._by_group[(lot_id, int(hour), int(dow))] = tuple(value)
        model._by_lot = {k: tuple(v) for k, v in payload["by_lot"].items()}
        model._global = tuple(payload["global"])
        model._fitted = True
        return model
