"""Idempotent loader for campus configuration YAML files.

Usage (from backend/, with DB env configured):
    python -m scripts.load_campus_config                 # load every file in configs/campuses/
    python -m scripts.load_campus_config sample.yaml      # load one file, by name or path
"""

import argparse
import asyncio
import sys
from pathlib import Path

from app.config_loader import ConfigValidationError, load_campus_config_file, upsert_campus_config
from app.db import SessionLocal

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPUS_CONFIG_DIR = REPO_ROOT / "configs" / "campuses"


def _resolve_paths(names: list[str]) -> list[Path]:
    if not names:
        return sorted(CAMPUS_CONFIG_DIR.glob("*.yaml"))
    resolved = []
    for name in names:
        candidate = Path(name)
        if not candidate.exists():
            candidate = CAMPUS_CONFIG_DIR / name
        resolved.append(candidate)
    return resolved


async def _load_all(paths: list[Path]) -> int:
    failures = 0
    async with SessionLocal() as session:
        for path in paths:
            try:
                config = load_campus_config_file(path)
            except ConfigValidationError as exc:
                failures += 1
                print(f"[FAIL] {path}: {len(exc.errors)} error(s)", file=sys.stderr)
                for error in exc.errors:
                    print(f"    - {error}", file=sys.stderr)
                continue
            version = await upsert_campus_config(session, config)
            print(f"[OK] {path}: campus {config.campus_id!r} loaded at configuration_version={version}")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="Campus YAML file name(s) or path(s)")
    args = parser.parse_args()

    paths = _resolve_paths(args.files)
    if not paths:
        print(f"No campus config files found in {CAMPUS_CONFIG_DIR}", file=sys.stderr)
        raise SystemExit(1)

    failures = asyncio.run(_load_all(paths))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
