"""B1 baseline: predicts a lot's historical mean occupancy for the same
(hour, day_of_week) bucket. No trend, no recent-state awareness -- the
floor every richer model should beat. Prediction intervals are true
empirical quantile regression: the lower_q/upper_q percentile of that same
group's historical target values, not a normal-distribution guess."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

MODEL_VERSION = "hist_avg-v1"


class HistoricalAverageModel:
    def __init__(self) -> None:
        self._by_group: dict[tuple, list[float]] = {}
        self._by_lot: dict[str, list[float]] = {}
        self._global: list[float] = []
        self._fitted = False

    def fit(self, train_df: pd.DataFrame, feature_cols: list[str], target_col: str = "target") -> None:
        self._by_group = {
            key: group[target_col].tolist() for key, group in train_df.groupby(["lot_id", "hour", "day_of_week"])
        }
        self._by_lot = {lot_id: group[target_col].tolist() for lot_id, group in train_df.groupby("lot_id")}
        self._global = train_df[target_col].tolist()
        self._fitted = True

    def _values_for(self, row: pd.Series) -> list[float]:
        key = (row["lot_id"], int(row["hour"]), int(row["day_of_week"]))
        if key in self._by_group:
            return self._by_group[key]
        if row["lot_id"] in self._by_lot:
            return self._by_lot[row["lot_id"]]
        return self._global

    def predict(self, df: pd.DataFrame, feature_cols: list[str]) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("model has not been fitted or loaded")
        return np.array([float(np.mean(self._values_for(row))) for _, row in df.iterrows()])

    def predict_interval(
        self, df: pd.DataFrame, feature_cols: list[str], lower_q: float = 0.1, upper_q: float = 0.9
    ) -> tuple[np.ndarray, np.ndarray]:
        # Empirical quantile regression: the group's own historical
        # lower_q/upper_q percentile, not a distributional assumption.
        if not self._fitted:
            raise RuntimeError("model has not been fitted or loaded")
        lower = np.array([float(np.quantile(self._values_for(row), lower_q)) for _, row in df.iterrows()])
        upper = np.array([float(np.quantile(self._values_for(row), upper_q)) for _, row in df.iterrows()])
        return lower, upper

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
            model._by_group[(lot_id, int(hour), int(dow))] = value
        model._by_lot = payload["by_lot"]
        model._global = payload["global"]
        model._fitted = True
        return model
