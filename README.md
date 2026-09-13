# ParkingNav-X

Campus parking platform. MODULE 0 built the application shell and API foundation; MODULE 1 adds campus configuration (campuses, gates, roads, parking lots, destinations, events, and the routable graph derived from them). No VIT-AP operational field data is included yet — only a fabricated `sample` campus for development, clearly labeled as such.

## Structure

- `frontend/`: one Vite + React app for public routes and protected `/admin` routes.
- `backend/`: FastAPI API with routes -> services -> repositories -> database layering.
- `configs/campuses/`: one YAML file per campus, loaded idempotently via `backend/scripts/load_campus_config.py`.
- `ml/`, `simulation/`, `optimization/`: reserved module boundaries.
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

Occupancy tracking, GPS/CV field collection pipelines (Module 1B), live map integration, prediction, optimization/routing logic, admin authentication, real VIT-AP survey data, external datasets, and production deployment are intentionally deferred to later modules. No accuracy or real-world benefit is claimed.