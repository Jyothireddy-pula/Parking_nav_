"""B2 baseline: predicts the target as the lot's own rolling_mean_6
feature (the 30-min trailing average already computed in features.py) --
i.e. "whatever the recent trend has been, continue it." Slightly more
informed than HistoricalAverage since it reacts to the current state
instead of only the calendar slot."""

import json
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

MODEL_VERSION = "moving_avg-v1"

FORECAST_FEATURE = "rolling_mean_6"


class MovingAverageModel:
    def __init__(self) -> None:
        self._residual_std: float | None = None
        self._fitted = False

    def fit(self, train_df: pd.DataFrame, feature_cols: list[str], target_col: str = "target") -> None:
        if FORECAST_FEATURE not in train_df.columns:
            raise ValueError(f"MovingAverageModel requires the {FORECAST_FEATURE!r} feature to be present")
        residuals = train_df[target_col].to_numpy() - train_df[FORECAST_FEATURE].to_numpy()
        self._residual_std = float(np.std(residuals)) or 0.0
        self._fitted = True

    def predict(self, df: pd.DataFrame, feature_cols: list[str]) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("model has not been fitted or loaded")
        return df[FORECAST_FEATURE].to_numpy(dtype=float)

    def predict_interval(
        self, df: pd.DataFrame, feature_cols: list[str], lower_q: float = 0.1, upper_q: float = 0.9
    ) -> tuple[np.ndarray, np.ndarray]:
        if not self._fitted:
            raise RuntimeError("model has not been fitted or loaded")
        point = self.predict(df, feature_cols)
        z_lo, z_hi = NormalDist().inv_cdf(lower_q), NormalDist().inv_cdf(upper_q)
        return point + z_lo * self._residual_std, point + z_hi * self._residual_std

    def save(self, path: str) -> None:
        if not self._fitted:
            raise RuntimeError("refusing to save an unfitted model")
        Path(path).write_text(json.dumps({"residual_std": self._residual_std}), encoding="utf-8")

    @classmethod
    def load(cls, path: str) -> "MovingAverageModel":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        model = cls()
        model._residual_std = payload["residual_std"]
        model._fitted = True
        return model
