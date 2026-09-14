# Prediction Engine — Module 9

Predicts future occupancy. Never decides anything — no allocation, no
routing, no optimization; that stays out of this module entirely. Data
prep and model training live together as one pipeline
(`ml/prediction/pipeline.py`), not separately-run stages that could drift
out of sync.

## 1. Data prep

`ml/prediction/features.py`: raw per-lot readings (any cadence) are
bucketed to 5-minute windows (`bucket_to_5min`, forward-filled across gaps
up to 15 minutes, longer gaps left genuinely missing and dropped — never
invented). `build_features` then engineers, per bucket: hour, day-of-week,
occupancy lags (5/15/30 min back), a one-step demand-change lag, a 30-min
rolling mean/std, and — when the dataset actually has them — gate inflow
and event intensity. The target is occupancy at the requested horizon
ahead. Every feature is tagged with its lag in `FEATURE_LAG_BUCKETS`
(`ml/prediction/features.py`); a "calendar" feature (hour/day-of-week, or a
target-window event intensity that's knowable in advance) is exempt since
it describes the *future* timestamp, not past data.

**Leakage check** (`ml/prediction/leakage.py`): every row must have
`asof_ts < target_ts`, and every declared feature must either be a
calendar feature or have a registered lag ≥ 1 bucket — i.e. built only
from data strictly before the row it describes. A feature with lag 0 (or
missing from the registry entirely — the shape an actual leak takes) fails
the check. Tested directly: `test_leakage_check_catches_a_broken_feature_with_lag_zero`
constructs a feature that *is* the target value and confirms the check
rejects it.

**Split**: `ml/prediction/split.py`'s `chronological_split` — never a
random shuffle, which would leak future buckets into training for a
time-series problem. Default 70/15/15 train/val/test.

## 2. Bootstrapping — EXTERNAL UCI "Parking Birmingham" dataset

Verified current download location (checked live in this session —
`curl -sI` on this exact URL returned HTTP 200; re-verify before a real
retraining run, UCI URLs can move):

    https://archive.ics.uci.edu/static/public/482/parking+birmingham.zip

UCI dataset ID 482. 35,717 rows, 30 car parks operated by NCP for
Birmingham City Council, 2016-10-04 to 2016-12-19, columns
`SystemCodeNumber, Capacity, Occupancy, LastUpdated`, UK Open Government
Licence. `ml/prediction/datasets/uci_birmingham.py` downloads and parses
it into this pipeline's standard schema.

**Labeling rule, permanent, no exceptions** (same rule as Module 5's
PKLot/CNRPark-EXT): any model trained on this dataset is trained on data
labeled `EXTERNAL`. That label never changes. It proves the pipeline code
and model architecture work; it says nothing about accuracy at VIT-AP.

**This actually ran in this session** — unlike Module 5's PKLot/CNRPark-EXT
(too large to fetch/train here), this dataset is 1.4MB and trains in
seconds, so a real run happened: `python -m prediction.train_external
--cache-dir ../data/external/uci_parking_birmingham`. Results in §5.

## 3. Real VIT-AP data

`prediction/train_real.py` (repo root, requires the shared backend/ml
venv) queries Module 4's `observations` table for `source_label == "REAL"`
rows for one campus, joins each lot's current `usable_capacity` from
Module 1 config, and runs the identical pipeline — never blended with the
UCI run, always reported separately.

**This also actually ran in this session** against `vitap` (after loading
`configs/campuses/vitap.yaml` into a throwaway database) — see §5 for the
real, printed result. As of this session, no physical VIT-AP field data
collection (Module 1B's GPS survey, Module 2's manual counts) has
happened, so real VIT-AP data is 0 rows. The script's floor for training
at all is `MIN_ROWS_TO_TRAIN = 500` — a small pilot floor, not a validated
sufficiency bar. Re-run once field collection has produced real rows.

## 4. Models

`ml/prediction/models/`:

- **HistoricalAverage** (B1): mean occupancy for the same
  (lot, hour, day-of-week) bucket, falling back to a lot-level then
  global mean for unseen combinations. No trend, no recent-state
  awareness — the floor every richer model should beat.
- **MovingAverage** (B2): predicts the lot's own 30-min trailing rolling
  mean directly — "continue the recent trend." Prediction interval from
  the model's own training-residual spread (normal approximation).
- **XGBoost** (B3): gradient-boosted trees, config-driven hyperparameters
  (`ml/prediction/config.py`: `n_estimators`, `max_depth`, `learning_rate`,
  `subsample`, `colsample_bytree`). Prediction intervals via native
  quantile regression (`reg:quantileerror`, xgboost ≥ 2.0) — a separate
  booster per quantile (0.1, 0.5, 0.9 by default); the point estimate is
  the median booster.

Both horizons (15-min, 30-min) are trained and evaluated independently —
a horizon is not a feature, it's a separate model per (model family,
horizon) pair, since the feature/target relationship genuinely differs.

**Versioning** (`ml/prediction/versioning.py`): every stored evaluation and
prediction carries `model_version` (per model family, bumped on
architecture/hyperparameter changes), `dataset_version` (a hash of
dataset label + row count + covered time range — changes whenever the
underlying rows change), `preprocessing_version`, and `feature_version`
(both bumped when `split.py`/`features.py` change), plus horizon,
prediction timestamp, target timestamp, evaluation metrics, and the
evaluation's own time range.

## 5. Report

### External-data (UCI Parking Birmingham) run — measured, this session

`dataset_version=uci_parking_birmingham-d1e76e962beb`, 35,717 raw rows,
2016-10-04 to 2016-12-19.

| horizon | model | MAE | RMSE | R² | WAPE | MAPE | n |
|---|---|---|---|---|---|---|---|
| 15 min | historical_average | 136.44 | 238.75 | 0.891 | 0.192 | 0.314 | 21,227 |
| 15 min | moving_average | 105.98 | 232.43 | 0.896 | 0.149 | 0.455 | 21,227 |
| 15 min | xgboost | **48.11** | **130.05** | **0.968** | **0.068** | 0.239 | 21,227 |
| 30 min | historical_average | 130.21 | 230.43 | 0.898 | 0.183 | 0.281 | 21,213 |
| 30 min | moving_average | 149.36 | 303.92 | 0.823 | 0.210 | 0.625 | 21,213 |
| 30 min | xgboost | **66.43** | **142.16** | **0.961** | **0.094** | 0.292 | 21,213 |

XGBoost clearly outperforms both baselines at both horizons on this
dataset. MAPE is reported but is a noisy metric here — several UCI car
parks have near-zero occupancy stretches, making percentage error
volatile even though it's technically defined (no exact-zero rows in the
test split). These numbers describe UCI Birmingham car parks in
Oct–Dec 2016, operated by NCP — not VIT-AP, not any other campus.

### Real VIT-AP data run — measured, this session

    [INFO] found 0 REAL observation(s) for campus='vitap'
    [INSUFFICIENT DATA] 0 real row(s) is below this pilot's floor of 500
    to train/evaluate meaningfully. No model trained, no metric reported.

No model trained, no metrics computed, none claimed. This is the honest
result of running the real pipeline against the real (currently empty)
VIT-AP dataset — not a placeholder or a stand-in number. Re-run
`prediction/train_real.py --campus-id vitap` once Module 1B/Module 2 field
collection produces real observations; `MIN_ROWS_TO_TRAIN` may also need
revisiting once there's a real error curve to look at.

## Intentionally not implemented

Automatic re-training on a schedule, a model registry UI, drift detection
against live data, and the confidence-band thresholds' validation against
real VIT-AP error are all out of scope here. `PredictionService`'s
confidence bands (`backend/app/services/prediction.py`:
`HIGH_MAE_FRACTION = 0.10`, `MODERATE_MAE_FRACTION = 0.25`) are a documented
starting policy, structurally identical to Module 5's CV promotion
threshold — not yet validated against real error, since no real evaluation
exists to validate it against.

**Known Docker gap**: `backend/app/services/prediction.py` imports
`ml/prediction`'s feature-building code at request time. That import is
only reached once a model is actually registered under
`PARKINGNAVX_PREDICTION_MODEL_DIR` — which nothing in this repo does yet
(see §5's real-data result) — so it hasn't bitten in practice. But
`docker/` (Module 0) builds the backend container from `./backend` alone,
without the `ml` package, so a deployment that *does* register a trained
model would hit an `ImportError` inside that container until the backend
image is updated to also install `ml`. Local dev is unaffected (this
repo's shared `.venv` has both installed) and CI's `backend` job now
installs both too.
