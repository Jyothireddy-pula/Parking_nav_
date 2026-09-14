"""Orchestrates one dataset through: bucket -> feature build -> leakage
check -> chronological split -> train HistoricalAverage, MovingAverage,
XGBoost -> evaluate each on the held-out test split. Data prep and model
training deliberately live together here as one pipeline, per Module 9's
spec, rather than as separately-run stages that could drift out of sync.

Returns a report keyed by horizon -> model_name -> a result carrying the
fitted model, its metrics, and every version tag Module 9 requires to be
stored with a prediction (model/dataset/preprocessing/feature versions,
horizon, evaluation time range).
"""

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from prediction.evaluate import regression_metrics
from prediction.features import bucket_to_5min, build_features, feature_columns
from prediction.leakage import check_no_leakage
from prediction.models.historical_average import HistoricalAverageModel
from prediction.models.moving_average import MovingAverageModel
from prediction.models.xgboost_model import XGBoostQuantileModel
from prediction.split import chronological_split
from prediction.versioning import (
    FEATURE_VERSION,
    MODEL_VERSIONS,
    PREPROCESSING_VERSION,
    dataset_version,
)


@dataclass
class ModelResult:
    model_name: str
    model: object
    metrics: dict
    model_version: str
    dataset_version: str
    preprocessing_version: str
    feature_version: str
    horizon_minutes: int
    evaluation_start: datetime
    evaluation_end: datetime
    evaluation_sample_size: int


@dataclass
class PipelineReport:
    dataset_label: str
    dataset_version: str
    results: dict  # horizon_minutes -> {model_name -> ModelResult}


def run_pipeline(
    raw_df: pd.DataFrame,
    dataset_label: str,
    horizons_minutes: list[int],
    train_frac: float = 0.7,
    val_frac: float = 0.15,
    xgboost_hyperparameters: dict | None = None,
    lower_q: float = 0.1,
    upper_q: float = 0.9,
) -> PipelineReport:
    bucketed = bucket_to_5min(raw_df)
    ds_version = dataset_version(dataset_label, bucketed)

    results: dict[int, dict[str, ModelResult]] = {}
    for horizon in horizons_minutes:
        featured = build_features(bucketed, horizon)
        cols = feature_columns(featured)
        check_no_leakage(featured, cols)

        train, _val, test = chronological_split(featured, train_frac, val_frac)
        if train.empty or test.empty:
            raise ValueError(
                f"not enough data for horizon={horizon} to form a non-empty train/test split "
                f"(got {len(featured)} feature rows total)"
            )

        results[horizon] = {}

        historical = HistoricalAverageModel()
        historical.fit(train, cols)
        results[horizon]["historical_average"] = _evaluate(
            "historical_average", historical, test, cols, MODEL_VERSIONS["historical_average"],
            ds_version, horizon,
        )

        moving = MovingAverageModel()
        moving.fit(train, cols)
        results[horizon]["moving_average"] = _evaluate(
            "moving_average", moving, test, cols, MODEL_VERSIONS["moving_average"], ds_version, horizon
        )

        xgb_model = XGBoostQuantileModel(xgboost_hyperparameters)
        xgb_model.fit_with_quantiles(train, cols, lower_q=lower_q, upper_q=upper_q)
        results[horizon]["xgboost"] = _evaluate(
            "xgboost", xgb_model, test, cols, MODEL_VERSIONS["xgboost"], ds_version, horizon
        )

    return PipelineReport(dataset_label=dataset_label, dataset_version=ds_version, results=results)


def _evaluate(
    name: str, model, test: pd.DataFrame, cols: list[str], model_version: str, ds_version: str, horizon: int
) -> ModelResult:
    predictions = model.predict(test, cols)
    metrics = regression_metrics(test["target"].to_numpy(), predictions)
    return ModelResult(
        model_name=name,
        model=model,
        metrics=metrics,
        model_version=model_version,
        dataset_version=ds_version,
        preprocessing_version=PREPROCESSING_VERSION,
        feature_version=FEATURE_VERSION,
        horizon_minutes=horizon,
        evaluation_start=test["asof_ts"].min().to_pydatetime(),
        evaluation_end=test["asof_ts"].max().to_pydatetime(),
        evaluation_sample_size=len(test),
    )
