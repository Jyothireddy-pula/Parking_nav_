# ParkingNav-X

MODULE 0 foundation for a campus parking platform. This repository intentionally contains only the application shell, API health contract, database wiring, and development infrastructure. No VIT-AP operational data or domain tables are included.

## Structure

- `frontend/`: one Vite + React app for public routes and protected `/admin` routes.
- `backend/`: FastAPI API with routes -> services -> repositories -> database layering.
- `ml/`, `simulation/`, `optimization/`: reserved module boundaries.
- `data/{raw,processed,sample,external}/`: provenance-scoped data locations.
- `experiments/`, `configs/`, `tests/`, `docs/`, `docker/`: reserved foundation locations.

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

This starts PostgreSQL 16, the reload-enabled backend on port 8000, and the Vite frontend on port 5173. The database is named `parkingnavx`. Apply the empty baseline migration from `backend` with `alembic upgrade head` when database migrations are needed.

## Intentionally not implemented

Parking lots, gates, roads, occupancy, GPS/map integration, CV, prediction, optimization, admin authentication, campus configuration, field collection, external datasets, and production deployment are intentionally deferred to later modules. No accuracy or real-world benefit is claimed.