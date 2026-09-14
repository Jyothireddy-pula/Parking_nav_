"""Module 9 real-data training run: trains against whatever REAL VIT-AP
observations actually exist in Module 4's `observations` table (source_label
== "REAL") for one campus. Reports its results separately from
ml/prediction/train_external.py's UCI run -- never blended, per Module 9's
spec.

As of this session, no physical VIT-AP field data collection (Module 1B's
GPS survey, Module 2's manual counts) has happened, so this almost
certainly reports "insufficient real data" rather than a trained model --
that is the honest result, not a bug to work around by substituting
synthetic or external numbers for it. See docs/PREDICTION.md's Report
section for what running this actually produced.

Requires the backend's virtualenv (this repo's shared .venv, where both
parkingnavx-backend and parkingnavx-ml are pip-installed editable).

Usage:
    python prediction/train_real.py --campus-id vitap
"""

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
ML_ROOT = REPO_ROOT / "ml"
for path in (BACKEND_ROOT, ML_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models.ingestion import Observation  # noqa: E402
from app.services.campus_config import CampusNotFoundError  # noqa: E402
from app.repositories.campus_config import CampusConfigRepository  # noqa: E402

from prediction.config import HORIZONS_MINUTES, TRAIN_FRAC, VAL_FRAC, XGBOOST_HYPERPARAMETERS  # noqa: E402
from prediction.datasets.real_observations import from_observation_rows  # noqa: E402
from prediction.pipeline import run_pipeline  # noqa: E402

MIN_ROWS_TO_TRAIN = 500  # small pilot floor, not a validated sufficiency bar -- see docs/PREDICTION.md


async def _fetch_real_rows(campus_id: str) -> list[dict]:
    config_repo = CampusConfigRepository()
    async with SessionLocal() as session:
        campus = await config_repo.get_campus(session, campus_id)
        if campus is None:
            raise CampusNotFoundError(campus_id)

        capacities = {
            lot.parking_lot_id: lot.usable_capacity
            for lot in await config_repo.list_parking_lots(session, campus_id)
        }

        result = await session.execute(
            select(Observation).where(
                Observation.campus_id == campus_id,
                Observation.source_label == "REAL",
                Observation.parking_lot_id.is_not(None),
                Observation.occupied_spaces.is_not(None),
            )
        )
        rows = []
        for obs in result.scalars().all():
            capacity = capacities.get(obs.parking_lot_id)
            if capacity is None:
                continue  # a lot no longer in the current config -- skip, don't guess its capacity
            rows.append(
                {
                    "parking_lot_id": obs.parking_lot_id,
                    "timestamp": obs.timestamp,
                    "occupied_spaces": obs.occupied_spaces,
                    "capacity": capacity,
                }
            )
        return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--campus-id", required=True)
    args = parser.parse_args()

    try:
        rows = asyncio.run(_fetch_real_rows(args.campus_id))
    except CampusNotFoundError:
        print(f"[FAIL] campus {args.campus_id!r} not found", file=sys.stderr)
        raise SystemExit(1)

    print(f"[INFO] found {len(rows)} REAL observation(s) for campus={args.campus_id!r}")
    if len(rows) < MIN_ROWS_TO_TRAIN:
        print(
            f"[INSUFFICIENT DATA] {len(rows)} real row(s) is below this pilot's floor of "
            f"{MIN_ROWS_TO_TRAIN} to train/evaluate meaningfully. No model trained, no metric "
            f"reported -- reporting a number here would misrepresent how little real data backs it. "
            f"Re-run once Module 1B/Module 2 field collection has produced more real observations."
        )
        raise SystemExit(0)

    raw_df = from_observation_rows(rows)
    report = run_pipeline(
        raw_df,
        dataset_label=f"vitap_real_{args.campus_id}",
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
            print(f"  {name:20s} mae={m['mae']:.2f} rmse={m['rmse']:.2f} n={m['n']}")


if __name__ == "__main__":
    main()
