"""B3 model: gradient-boosted trees via XGBoost, config-driven
hyperparameters, native quantile regression (xgboost>=2.0's
reg:quantileerror) for the prediction interval -- a separate booster per
quantile (lower, median, upper), point estimate = the median booster."""

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb

MODEL_VERSION = "xgboost-v1"

DEFAULT_HYPERPARAMETERS = {
    "n_estimators": 200,
    "max_depth": 4,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
}


class XGBoostQuantileModel:
    def __init__(self, hyperparameters: dict | None = None) -> None:
        self._params = {**DEFAULT_HYPERPARAMETERS, **(hyperparameters or {})}
        self._boosters: dict[float, xgb.XGBRegressor] = {}
        self._fitted = False

    def fit(self, train_df: pd.DataFrame, feature_cols: list[str], target_col: str = "target") -> None:
        self.fit_with_quantiles(train_df, feature_cols, target_col, lower_q=0.1, upper_q=0.9)

    def fit_with_quantiles(
        self,
        train_df: pd.DataFrame,
        feature_cols: list[str],
        target_col: str = "target",
        lower_q: float = 0.1,
        upper_q: float = 0.9,
    ) -> None:
        X = train_df[feature_cols].to_numpy(dtype=float)
        y = train_df[target_col].to_numpy(dtype=float)

        for quantile in (lower_q, 0.5, upper_q):
            booster = xgb.XGBRegressor(
                objective="reg:quantileerror",
                quantile_alpha=quantile,
                n_estimators=self._params["n_estimators"],
                max_depth=self._params["max_depth"],
                learning_rate=self._params["learning_rate"],
                subsample=self._params["subsample"],
                colsample_bytree=self._params["colsample_bytree"],
            )
            booster.fit(X, y)
            self._boosters[quantile] = booster
        self._fitted = True
        self._lower_q, self._upper_q = lower_q, upper_q

    def predict(self, df: pd.DataFrame, feature_cols: list[str]) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("model has not been fitted or loaded")
        X = df[feature_cols].to_numpy(dtype=float)
        return self._boosters[0.5].predict(X)

    def predict_interval(
        self, df: pd.DataFrame, feature_cols: list[str], lower_q: float = 0.1, upper_q: float = 0.9
    ) -> tuple[np.ndarray, np.ndarray]:
        if not self._fitted:
            raise RuntimeError("model has not been fitted or loaded")
        if lower_q not in self._boosters or upper_q not in self._boosters:
            raise ValueError(
                f"model was trained for quantiles {sorted(self._boosters)}, not ({lower_q}, {upper_q})"
            )
        X = df[feature_cols].to_numpy(dtype=float)
        return self._boosters[lower_q].predict(X), self._boosters[upper_q].predict(X)

    def save(self, path: str) -> None:
        # joblib-pickles the sklearn wrapper objects directly rather than
        # xgboost's own save_model -- xgboost 2.1.x's XGBRegressor.save_model
        # raises on a plain (non-classifier/regressor-mixin) wrapper state;
        # joblib sidesteps that entirely and is already this project's
        # standard model-artifact format (see ml/cv/classifier.py).
        if not self._fitted:
            raise RuntimeError("refusing to save an unfitted model")
        base = Path(path)
        base.mkdir(parents=True, exist_ok=True)
        joblib.dump(self._boosters, base / "boosters.joblib")
        (base / "quantiles.txt").write_text(f"{self._lower_q},{self._upper_q}", encoding="utf-8")

    @classmethod
    def load(cls, path: str) -> "XGBoostQuantileModel":
        base = Path(path)
        model = cls()
        model._boosters = joblib.load(base / "boosters.joblib")
        lower_q, upper_q = (float(x) for x in (base / "quantiles.txt").read_text(encoding="utf-8").split(","))
        model._fitted = True
        model._lower_q, model._upper_q = lower_q, upper_q
        return model
