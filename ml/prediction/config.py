"""Config-driven knobs for Module 9 training runs. A real deployment would
load this from a YAML file the way configs/campuses/*.yaml drives Module
1; kept as a plain dict here since no other module has needed a
generic non-campus config file yet -- avoids inventing a second config
loading mechanism for one module."""

HORIZONS_MINUTES = [15, 30]

TRAIN_FRAC = 0.7
VAL_FRAC = 0.15  # remainder (0.15) is the test split

XGBOOST_HYPERPARAMETERS = {
    "n_estimators": 200,
    "max_depth": 4,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
}

PREDICTION_INTERVAL_LOWER_Q = 0.1
PREDICTION_INTERVAL_UPPER_Q = 0.9
