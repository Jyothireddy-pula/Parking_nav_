"""Bootstrapping run: trains and evaluates all three Module 9 models
against the EXTERNAL UCI "Parking Birmingham" dataset. Prints a metrics
table; never blended with (or presented as) real VIT-AP results -- see
train_real.py and docs/PREDICTION.md's Report section for that.

Usage:
    python -m prediction.train_external --cache-dir ../data/external/uci_parking_birmingham
"""

import argparse
from pathlib import Path

from prediction.config import HORIZONS_MINUTES, TRAIN_FRAC, VAL_FRAC, XGBOOST_HYPERPARAMETERS
from prediction.datasets import uci_birmingham
from prediction.pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cache-dir", type=Path, default=Path("../data/external/uci_parking_birmingham"))
    args = parser.parse_args()

    csv_path = uci_birmingham.download(args.cache_dir)
    raw_df = uci_birmingham.load(csv_path)
    print(f"[OK] loaded {len(raw_df)} rows from {csv_path}")

    report = run_pipeline(
        raw_df,
        dataset_label=uci_birmingham.DATASET_LABEL,
        horizons_minutes=HORIZONS_MINUTES,
        train_frac=TRAIN_FRAC,
        val_frac=VAL_FRAC,
        xgboost_hyperparameters=XGBOOST_HYPERPARAMETERS,
    )

    print(f"\ndataset_version={report.dataset_version}")
    for horizon, models in report.results.items():
        print(f"\n== horizon={horizon}min ==")
        for name, result in models.items():
            m = result.metrics
            r2 = f"{m['r2']:.3f}" if m["r2"] is not None else "n/a"
            wape = f"{m['wape']:.3f}" if m["wape"] is not None else "n/a"
            mape = f"{m['mape']:.3f}" if m["mape"] is not None else "n/a"
            print(
                f"  {name:20s} mae={m['mae']:.2f} rmse={m['rmse']:.2f} r2={r2} wape={wape} mape={mape} "
                f"n={m['n']}"
            )


if __name__ == "__main__":
    main()
