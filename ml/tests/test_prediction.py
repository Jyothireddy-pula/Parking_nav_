"""Module 9 tests: leakage check catches a broken feature; baseline
sanity; XGBoost trains without crashing; metric correctness on a toy
example. Uses a small SYNTHETIC generated time series -- proves the code
path works, never presented as PKLot/UCI/VIT-AP accuracy. See
docs/PREDICTION.md."""

import numpy as np
import pandas as pd
import pytest

from prediction.evaluate import regression_metrics
from prediction.features import (
    CALENDAR_FEATURES,
    FEATURE_LAG_BUCKETS,
    bucket_to_5min,
    build_features,
    feature_columns,
)
from prediction.leakage import LeakageError, check_no_leakage
from prediction.models.historical_average import HistoricalAverageModel
from prediction.models.moving_average import MovingAverageModel
from prediction.models.xgboost_model import XGBoostQuantileModel
from prediction.pipeline import run_pipeline
from prediction.split import chronological_split


def _synthetic_raw_df(n_days: int = 3, lots: tuple[str, ...] = ("lot-a", "lot-b")) -> pd.DataFrame:
    """5-min-resolution, deterministic sinusoidal occupancy per lot --
    proves the pipeline code works end to end, not a claim about any real
    parking lot's behavior."""

    rng = np.random.default_rng(seed=7)
    start = pd.Timestamp("2024-01-01", tz="UTC")
    n_buckets = n_days * 24 * 12  # 5-min buckets
    timestamps = pd.date_range(start, periods=n_buckets, freq="5min")

    frames = []
    for i, lot_id in enumerate(lots):
        capacity = 100 + i * 20
        hours = timestamps.hour + timestamps.minute / 60
        occupied = capacity * (0.5 + 0.4 * np.sin((hours - 6) / 24 * 2 * np.pi))
        occupied = np.clip(occupied + rng.normal(0, 2, n_buckets), 0, capacity).round()
        frames.append(pd.DataFrame({"lot_id": lot_id, "timestamp": timestamps, "occupied": occupied, "capacity": capacity}))
    return pd.concat(frames, ignore_index=True)


@pytest.fixture(scope="module")
def bucketed() -> pd.DataFrame:
    return bucket_to_5min(_synthetic_raw_df())


@pytest.fixture(scope="module")
def featured_15(bucketed: pd.DataFrame) -> pd.DataFrame:
    return build_features(bucketed, horizon_minutes=15)


# --- data prep ---


def test_bucket_to_5min_produces_one_row_per_lot_per_bucket(bucketed: pd.DataFrame) -> None:
    assert set(bucketed["lot_id"]) == {"lot-a", "lot-b"}
    diffs = bucketed[bucketed["lot_id"] == "lot-a"]["timestamp"].diff().dropna().unique()
    assert list(diffs) == [pd.Timedelta(minutes=5)]


def test_build_features_drops_rows_without_enough_lag_history(featured_15: pd.DataFrame) -> None:
    # rolling_mean_6 needs 6 prior buckets -- the first 6 buckets of each
    # lot can never have a valid feature row.
    per_lot_counts = featured_15.groupby("lot_id").size()
    raw_per_lot = 3 * 24 * 12
    assert (per_lot_counts < raw_per_lot).all()
    assert (per_lot_counts > 0).all()


def test_build_features_without_target_keeps_the_most_recent_rows(bucketed: pd.DataFrame) -> None:
    with_target = build_features(bucketed, horizon_minutes=15, require_target=True)
    without_target = build_features(bucketed, horizon_minutes=15, require_target=False)

    # The most recent buckets (no future data available yet) are dropped
    # when a target is required, but kept -- with target NaN -- when
    # building features for live serving.
    assert len(without_target) > len(with_target)
    assert without_target["target"].isna().any()
    kept_rows = without_target.dropna(subset=feature_columns(without_target))
    assert not kept_rows.empty


def test_chronological_split_does_not_reorder_or_lose_rows(featured_15: pd.DataFrame) -> None:
    train, val, test = chronological_split(featured_15, train_frac=0.7, val_frac=0.15)
    assert len(train) + len(val) + len(test) == len(featured_15)
    assert train["asof_ts"].max() <= val["asof_ts"].min()
    assert val["asof_ts"].max() <= test["asof_ts"].min()


# --- leakage check ---


def test_leakage_check_passes_on_correctly_built_features(featured_15: pd.DataFrame) -> None:
    cols = feature_columns(featured_15)
    check_no_leakage(featured_15, cols)  # must not raise


def test_leakage_check_catches_a_broken_feature_with_lag_zero(featured_15: pd.DataFrame) -> None:
    cols = [*feature_columns(featured_15), "leaked_current_value"]
    broken = featured_15.copy()
    broken["leaked_current_value"] = broken["target"]  # a feature that IS the current/target value: lag 0

    with pytest.raises(LeakageError):
        check_no_leakage(broken, cols)


def test_leakage_check_catches_asof_not_before_target() -> None:
    df = pd.DataFrame({"asof_ts": [pd.Timestamp("2024-01-01T00:10:00Z")], "target_ts": [pd.Timestamp("2024-01-01T00:05:00Z")]})
    with pytest.raises(LeakageError):
        check_no_leakage(df, [])


def test_event_type_and_event_intensity_both_become_features_when_present() -> None:
    ts = pd.date_range("2024-01-01", periods=40, freq="5min", tz="UTC")
    raw = pd.DataFrame(
        {
            "lot_id": "lot-a",
            "timestamp": ts,
            "occupied": [50 + i for i in range(40)],
            "capacity": 100,
            "event_type": ["game_day" if i > 20 else None for i in range(40)],
            "event_intensity": [1.5 if i > 20 else None for i in range(40)],
        }
    )
    bucketed = bucket_to_5min(raw)
    featured = build_features(bucketed, horizon_minutes=15)

    assert "has_event_target" in featured.columns
    assert "event_intensity_target" in featured.columns
    assert set(featured["has_event_target"].unique()) <= {0.0, 1.0}


def test_every_feature_in_the_registry_has_a_valid_lag_or_is_calendar() -> None:
    for name, lag in FEATURE_LAG_BUCKETS.items():
        assert lag >= 1, f"{name} has an invalid lag"
    assert "hour" in CALENDAR_FEATURES and "day_of_week" in CALENDAR_FEATURES


# --- baseline sanity ---


def test_historical_average_baseline_beats_trivial_zero_prediction(featured_15: pd.DataFrame) -> None:
    cols = feature_columns(featured_15)
    train, _val, test = chronological_split(featured_15)

    model = HistoricalAverageModel()
    model.fit(train, cols)
    predictions = model.predict(test, cols)

    mae_model = np.mean(np.abs(predictions - test["target"].to_numpy()))
    mae_zero = np.mean(np.abs(test["target"].to_numpy()))
    assert mae_model < mae_zero


def test_historical_average_predict_interval_contains_the_point_estimate(featured_15: pd.DataFrame) -> None:
    cols = feature_columns(featured_15)
    train, _val, test = chronological_split(featured_15)
    model = HistoricalAverageModel()
    model.fit(train, cols)

    point = model.predict(test, cols)
    lower, upper = model.predict_interval(test, cols)
    assert (lower <= point).all()
    assert (point <= upper).all()


def test_moving_average_baseline_is_sane_on_a_smooth_series(featured_15: pd.DataFrame) -> None:
    cols = feature_columns(featured_15)
    train, _val, test = chronological_split(featured_15)

    model = MovingAverageModel()
    model.fit(train, cols)
    predictions = model.predict(test, cols)

    mae_model = np.mean(np.abs(predictions - test["target"].to_numpy()))
    mae_zero = np.mean(np.abs(test["target"].to_numpy()))
    assert mae_model < mae_zero


def test_moving_average_requires_rolling_mean_feature() -> None:
    model = MovingAverageModel()
    with pytest.raises(ValueError, match="rolling_mean_6"):
        model.fit(pd.DataFrame({"target": [1.0, 2.0]}), [])


# --- XGBoost trains without crashing ---


def test_xgboost_trains_and_predicts_without_crashing(featured_15: pd.DataFrame) -> None:
    cols = feature_columns(featured_15)
    train, _val, test = chronological_split(featured_15)

    model = XGBoostQuantileModel({"n_estimators": 20, "max_depth": 3})
    model.fit_with_quantiles(train, cols, lower_q=0.1, upper_q=0.9)

    point = model.predict(test, cols)
    lower, upper = model.predict_interval(test, cols)

    assert len(point) == len(test)
    assert np.all(np.isfinite(point))
    assert (lower <= upper).all()


def test_xgboost_beats_historical_average_on_the_synthetic_series(featured_15: pd.DataFrame) -> None:
    # Not a universal guarantee, but true for this smooth deterministic
    # synthetic series -- a sanity check that the richer model is actually
    # learning something, not a claim about real-world superiority.
    cols = feature_columns(featured_15)
    train, _val, test = chronological_split(featured_15)

    hist = HistoricalAverageModel()
    hist.fit(train, cols)
    hist_mae = np.mean(np.abs(hist.predict(test, cols) - test["target"].to_numpy()))

    xgb_model = XGBoostQuantileModel({"n_estimators": 50, "max_depth": 4})
    xgb_model.fit_with_quantiles(train, cols)
    xgb_mae = np.mean(np.abs(xgb_model.predict(test, cols) - test["target"].to_numpy()))

    assert xgb_mae < hist_mae


def test_xgboost_save_and_load_round_trips(featured_15: pd.DataFrame, tmp_path) -> None:
    cols = feature_columns(featured_15)
    train, _val, test = chronological_split(featured_15)

    model = XGBoostQuantileModel({"n_estimators": 10})
    model.fit_with_quantiles(train, cols)
    model.save(str(tmp_path / "model"))

    loaded = XGBoostQuantileModel.load(str(tmp_path / "model"))
    np.testing.assert_allclose(model.predict(test, cols), loaded.predict(test, cols))


# --- metric correctness on a toy example ---


def test_mae_and_rmse_on_a_hand_computed_toy_example() -> None:
    y_true = np.array([10.0, 20.0, 30.0])
    y_pred = np.array([12.0, 18.0, 33.0])
    # errors: 2, -2, 3 -> |errors|: 2, 2, 3 -> MAE = 7/3
    # squared errors: 4, 4, 9 -> mean = 17/3 -> RMSE = sqrt(17/3)
    metrics = regression_metrics(y_true, y_pred)

    assert metrics["mae"] == pytest.approx(7 / 3)
    assert metrics["rmse"] == pytest.approx((17 / 3) ** 0.5)
    assert metrics["n"] == 3


def test_r2_is_none_when_y_true_has_zero_variance() -> None:
    metrics = regression_metrics(np.array([5.0, 5.0, 5.0]), np.array([4.0, 5.0, 6.0]))
    assert metrics["r2"] is None


def test_mape_is_none_when_y_true_contains_a_zero() -> None:
    metrics = regression_metrics(np.array([0.0, 10.0]), np.array([1.0, 11.0]))
    assert metrics["mape"] is None
    assert metrics["wape"] is not None  # total actual (10) is still nonzero


def test_wape_matches_hand_computed_toy_example() -> None:
    y_true = np.array([10.0, 20.0, 30.0])
    y_pred = np.array([12.0, 18.0, 33.0])
    # WAPE = sum(|errors|) / sum(|y_true|) = 7 / 60
    metrics = regression_metrics(y_true, y_pred)
    assert metrics["wape"] == pytest.approx(7 / 60)


def test_regression_metrics_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError):
        regression_metrics(np.array([1.0, 2.0]), np.array([1.0]))


# --- pipeline / versioning end to end ---


def test_run_pipeline_end_to_end_on_synthetic_data() -> None:
    raw_df = _synthetic_raw_df(n_days=4)
    report = run_pipeline(raw_df, dataset_label="synthetic_test", horizons_minutes=[15, 30])

    assert set(report.results) == {15, 30}
    for horizon, models in report.results.items():
        assert set(models) == {"historical_average", "moving_average", "xgboost"}
        for result in models.values():
            assert result.horizon_minutes == horizon
            assert result.dataset_version == report.dataset_version
            assert result.metrics["mae"] >= 0
            assert result.evaluation_sample_size > 0
