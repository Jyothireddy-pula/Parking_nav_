"""Common interface every Module 9 model implements. predict_interval is
required, not optional: HistoricalAverage/MovingAverage produce a
distribution-free interval from their own residual spread rather than
skipping it -- every model in this module reports a prediction interval,
even the simple baselines."""

from typing import Protocol

import numpy as np
import pandas as pd


class PredictionModel(Protocol):
    def fit(self, train_df: pd.DataFrame, feature_cols: list[str], target_col: str = "target") -> None: ...

    def predict(self, df: pd.DataFrame, feature_cols: list[str]) -> np.ndarray: ...

    def predict_interval(
        self, df: pd.DataFrame, feature_cols: list[str], lower_q: float = 0.1, upper_q: float = 0.9
    ) -> tuple[np.ndarray, np.ndarray]: ...

    def save(self, path: str) -> None: ...

    @classmethod
    def load(cls, path: str) -> "PredictionModel": ...
