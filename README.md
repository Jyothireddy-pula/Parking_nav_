# ParkingNav-X

Campus parking platform. MODULE 0 built the application shell and API foundation; MODULE 1 adds campus configuration (campuses, gates, roads, parking lots, destinations, events, and the routable graph derived from them). No VIT-AP operational field data is included yet — only a fabricated `sample` campus for development, clearly labeled as such.

## Structure

- `frontend/`: one Vite + React app for public routes and protected `/admin` routes.
- `backend/`: FastAPI API with routes -> services -> repositories -> database layering.
- `configs/campuses/`: one YAML file per campus, loaded idempotently via `backend/scripts/load_campus_config.py`.
- `ml/cv/`: Module 5's occupancy classifier, space-polygon annotation, calibration, and camera pipeline. See `docs/CV.md`.
- `simulation/`, `optimization/`: reserved module boundaries.
- `data/{raw,processed,sample,external}/`: provenance-scoped data locations.
- `experiments/`, `tests/`, `docs/`, `docker/`: reserved foundation locations.

## Campus configuration (Module 1)

Each campus is defined in `configs/campuses/<campus_id>.yaml`: campus metadata, gates, roads (with GPS-surveyed geometry, not just endpoints), parking lots (capacity broken into usable/reserved/restricted/temporarily-unavailable, never derived from map area), destinations, and events. Loading a file validates it (duplicate IDs, malformed coordinates, invalid capacities, dangling road references, orphan nodes not connected to the routable graph) before writing anything, and reloading the same file is idempotent — `configuration_version` increments on every entity each time a file is loaded.

```powershell
cd backend
python -m scripts.load_campus_config sample.yaml   # or with no args, to load every file in configs/campuses/
```

Read the loaded data through `GET /api/v1/campuses/{campus_id}/{gates|roads|parking-lots|destinations|events}`.

Real VIT-AP coordinates and road geometry must come from Module 1B's GPS survey output — never typed in by hand or estimated from a screenshot.

Every future stored value must carry exactly one provenance label: `REAL`, `EXTERNAL`, `SYNTHETIC`, `SAMPLE`, or `COUNTERFACTUAL`. Missing observations remain `MISSING`; no values are guessed or silently imputed.

## Computer vision occupancy detection (Module 5)

`ml/cv/` — a logistic-regression classifier over handcrafted features (not a CNN — no verified GPU training run backs one), per-lot space polygon annotation, a frame→classify→aggregate→post pipeline that flags low-confidence (blurry or uncertain) frames instead of guessing, and a promotion rule that only trusts a lot's CV readings unsupervised (`cv_auto`) once a measured `cv_calibration_reports` row clears an explicit error threshold — otherwise every reading stays `cv_verified`. See `docs/CV.md` for dataset sources (PKLot/CNRPark-EXT, always labeled `EXTERNAL`), what has and hasn't actually been measured yet, and the recommended manual spot-check frequency.

```powershell
cd ml
python -m venv .venv  # or reuse backend/.venv
pip install -e ".[dev]"
pytest
```

## Run locally

Backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Frontend, in a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The API health endpoints are `http://localhost:8000/health` and `http://localhost:8000/api/v1/health`.

## Test and lint

```powershell
cd backend
pytest
ruff check .
cd ..\frontend
npm run lint
npm run build
```

## Docker Compose

```powershell
docker compose up --build
```

This starts PostgreSQL 16, the reload-enabled backend on port 8000, and the Vite frontend on port 5173. The database is named `parkingnavx`. Apply migrations from `backend` with `alembic upgrade head`, then load a campus config as shown above.

## Intentionally not implemented

Live map integration, prediction, optimization/routing logic, admin authentication, and production deployment are intentionally deferred to later modules. Real VIT-AP GPS survey data (Module 1B), real field-collected manual counts (Module 2), a real PKLot/CNRPark-EXT training run, and a real VIT-AP `cv_calibration_reports` row (Module 5) all require physical fieldwork or large external downloads that haven't happened in this environment — the tooling for all of them is built and tested against synthetic/sample stand-ins, clearly labeled as such. No accuracy or real-world benefit is claimed beyond what's actually been measured.