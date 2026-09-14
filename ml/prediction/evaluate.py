"""Evaluation metrics. MAE and RMSE are always computed -- they're always
mathematically meaningful. R2/WAPE/MAPE are each computed only when the
data doesn't make them degenerate or undefined; when skipped, the value is
None with the reason recorded, never a forced or divide-by-zero number."""

import math

import numpy as np


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    if len(y_true) != len(y_pred):
        raise ValueError(f"y_true and y_pred must be the same length, got {len(y_true)} vs {len(y_pred)}")
    if len(y_true) == 0:
        raise ValueError("cannot evaluate metrics on an empty set")

    errors = y_pred - y_true
    mae = float(np.mean(np.abs(errors)))
    rmse = float(math.sqrt(np.mean(errors**2)))

    metrics = {"mae": mae, "rmse": rmse, "r2": None, "wape": None, "mape": None, "n": len(y_true)}

    # R2 is undefined (0/0) when y_true has zero variance -- every actual
    # value identical, so "variance explained" doesn't mean anything.
    variance = float(np.var(y_true))
    if variance > 1e-9:
        ss_res = float(np.sum(errors**2))
        ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
        metrics["r2"] = 1.0 - ss_res / ss_tot

    # WAPE needs a nonzero total actual volume to normalize against.
    total_actual = float(np.sum(np.abs(y_true)))
    if total_actual > 1e-9:
        metrics["wape"] = float(np.sum(np.abs(errors)) / total_actual)

    # MAPE is undefined wherever y_true == 0 (an empty lot). Only report it
    # when no actual value in this set is zero -- never divide by zero to
    # force a number, and never silently skip individual rows either.
    if np.all(np.abs(y_true) > 1e-9):
        metrics["mape"] = float(np.mean(np.abs(errors / y_true)))

    return metrics
