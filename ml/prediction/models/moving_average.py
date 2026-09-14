"""B2 baseline: predicts the target as the lot's own rolling_mean_6
feature (the 30-min trailing average already computed in features.py) --
i.e. "whatever the recent trend has been, continue it." Slightly more
informed than HistoricalAverage since it reacts to the current state
instead of only the calendar slot. Prediction intervals are empirical
quantile regression on the training residuals (target - rolling_mean_6),
not a normal-distribution guess."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

MODEL_VERSION = "moving_avg-v1"

FORECAST_FEATURE = "rolling_mean_6"


class MovingAverageModel:
    def __init__(self) -> None:
        self._residuals: list[float] = []
        self._fitted = False

    def fit(self, train_df: pd.DataFrame, feature_cols: list[str], target_col: str = "target") -> None:
        if FORECAST_FEATURE not in train_df.columns:
            raise ValueError(f"MovingAverageModel requires the {FORECAST_FEATURE!r} feature to be present")
        residuals = train_df[target_col].to_numpy() - train_df[FORECAST_FEATURE].to_numpy()
        self._residuals = residuals.tolist()
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
        # Empirical quantile regression: the training residuals' own
        # lower_q/upper_q percentile, added to each row's point estimate.
        point = self.predict(df, feature_cols)
        lo, hi = np.quantile(self._residuals, [lower_q, upper_q])
        return point + lo, point + hi

    def save(self, path: str) -> None:
        if not self._fitted:
            raise RuntimeError("refusing to save an unfitted model")
        Path(path).write_text(json.dumps({"residuals": self._residuals}), encoding="utf-8")

    @classmethod
    def load(cls, path: str) -> "MovingAverageModel":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        model = cls()
        model._residuals = payload["residuals"]
        model._fitted = True
        return model
