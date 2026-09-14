"""Module 7 CLI: run one simulation scenario.

Requires the backend's virtualenv (this repo's shared .venv, where
`parkingnavx-backend` is pip-installed editable) so `app.*` is
importable, and a configured PARKINGNAVX_DATABASE_URL.

Usage:
    python simulation/run.py --scenario configs/scenarios/normal_day.yaml --seed 42
"""

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import SessionLocal  # noqa: E402
from app.scenario_loader import ScenarioValidationError, load_scenario_file  # noqa: E402
from app.services.simulation import ScenarioValidationFailedError, SimulationEngine  # noqa: E402


async def _run(scenario_path: Path, seed: int | None) -> int:
    try:
        scenario = load_scenario_file(scenario_path)
    except ScenarioValidationError as exc:
        print(f"[FAIL] {scenario_path}: {len(exc.errors)} error(s)", file=sys.stderr)
        for error in exc.errors:
            print(f"    - {error}", file=sys.stderr)
        return 1

    engine = SimulationEngine()
    async with SessionLocal() as session:
        try:
            run = await engine.run_and_store(session, scenario, seed=seed)
        except ScenarioValidationFailedError as exc:
            print(f"[FAIL] {scenario_path}: {len(exc.errors)} cross-entity error(s)", file=sys.stderr)
            for error in exc.errors:
                print(f"    - {error}", file=sys.stderr)
            return 1

    print(f"[OK] run_id={run.run_id} seed={run.seed} campus={run.campus_id} scenario={run.scenario_id}")
    print(f"     vehicles_total={run.metrics['vehicles_total']} "
          f"vehicles_parked={run.metrics['vehicles_parked']} overflow_count={run.metrics['overflow_count']}")
    print(f"     gate_wait_time_minutes: {run.metrics['gate_wait_time_minutes']}")
    print(f"     search_time_minutes: {run.metrics['search_time_minutes']}")
    print(f"     utilization_by_lot: {run.metrics['utilization_by_lot']}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=None, help="Overrides the scenario file's own seed")
    args = parser.parse_args()

    exit_code = asyncio.run(_run(args.scenario, args.seed))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
