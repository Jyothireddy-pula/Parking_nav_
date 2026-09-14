# ParkingNav-X

Campus parking platform. MODULE 0 built the application shell and API foundation; MODULE 1 adds campus configuration (campuses, gates, roads, parking lots, destinations, events, and the routable graph derived from them). Two campuses exist: a fully fabricated `sample` campus for development, and `vitap` — real VIT-AP building names/coordinates from OpenStreetMap, connected by fabricated placeholder roads/gate/lot until Module 1B's physical GPS walk replaces them. See `configs/campuses/vitap.yaml`'s header and `docs/DATA.md` for exactly what's real and what isn't.

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
python -m scripts.load_campus_config sample.yaml   # or vitap.yaml, or no args to load every file in configs/campuses/
```

Read the loaded data through `GET /api/v1/campuses/{campus_id}/{gates|roads|parking-lots|destinations|events}`.

Every gate, road, parking lot, and destination carries a required `provenance`: `REAL` (Module 1B GPS-walk/satellite verified, or Module 2 physical count), `EXTERNAL_MAP_REFERENCE` (pulled from a public map source — real, but not field-verified; never valid for a parking lot's capacity), or `SAMPLE` (fabricated placeholder). Live observations (Modules 3-4) use a separate set: `REAL`, `EXTERNAL`, `SYNTHETIC`, `SAMPLE`, `COUNTERFACTUAL`. Missing observations remain `MISSING`; no values are guessed or silently imputed.

## Computer vision occupancy detection (Module 5)

`ml/cv/` — a logistic-regression classifier over handcrafted features (not a CNN — no verified GPU training run backs one), per-lot space polygon annotation, a frame→classify→aggregate→post pipeline that flags low-confidence (blurry or uncertain) frames instead of guessing, and a promotion rule that only trusts a lot's CV readings unsupervised (`cv_auto`) once a measured `cv_calibration_reports` row clears an explicit error threshold — otherwise every reading stays `cv_verified`. See `docs/CV.md` for dataset sources (PKLot/CNRPark-EXT, always labeled `EXTERNAL`), what has and hasn't actually been measured yet, and the recommended manual spot-check frequency.

```powershell
cd ml
python -m venv .venv  # or reuse backend/.venv
pip install -e ".[dev]"
pytest
```

## Navigation & wayfinding (Module 6) — checkpoint

The frontend's home page (`frontend/src/Navigate.tsx`) is now a real Leaflet map — OpenStreetMap tiles by default, a satellite toggle, bounded/centered on VIT-AP's actual surveyed extent from Module 1B (not a guessed point) — with gate/destination/parking markers, live occupancy badges (green/orange/red, visually distinct when the reading is `STALE` vs `FRESH`), a gate picker with geolocation, destination search, and a "Report parking status" button posting to Module 4. Routes are drawn from the real road `geometry` (Module 1), concatenated leg by leg — never a straight line. Backend: `backend/app/services/navigation.py` builds an in-memory `networkx` graph per request from Module 1's `RouteEdge`s and Module 3's live closures; `GET /api/v1/campuses/{campus_id}/navigate/{route|nearest-parking|nearest-destination|search}` returns `409` with the standard error contract when no route exists, never a crash. Parking-to-destination is always two separate route legs (gate→lot, then lot→destination), matching how the frontend calls it.

```powershell
cd backend
pytest tests/test_navigation.py tests/test_navigation_routes.py
```

## Vehicle & parking simulation (Module 7)

A discrete-time (1-minute step) engine (`backend/app/services/simulation.py`) runs a SYNTHETIC scenario — arrivals, an event demand multiplier, gate/lot/road closures, capacity overrides, all validated against a real campus's gate/lot/road IDs — through the vehicle lifecycle (`approaching → searching → assigned → parked → leaving → completed`, the same states Module 3 uses). It calls Module 6's routing for real gate→lot travel times and an explicitly pluggable `AllocationStrategy` (`backend/app/services/allocation.py`) to pick a lot; the only strategy shipped here, `NearestAvailableLotStrategy`, is a placeholder — the real optimizer is Module 8's job. Same scenario + seed always produces identical output (tested), a lot's occupancy never exceeds its capacity (tested, under stress), and a closed gate/lot is never assigned to (tested). Every occupancy change writes into Module 3's Digital Twin tagged `source=simulation`/`provenance=SYNTHETIC` — run a simulation against a live campus's `campus_id` and its current parking state will visibly (but distinguishably) show simulated numbers until real data overwrites it again; use a non-live `campus_id` (e.g. `sample`) until a later module adds run-scoped twin isolation. Results are stored in `simulation_runs` and printed by the CLI.

```powershell
python simulation/run.py --scenario configs/scenarios/normal_day.yaml
python simulation/run.py --scenario configs/scenarios/high_demand_event.yaml --seed 99
```

Four starter scenarios ship in `configs/scenarios/`: `normal_day`, `high_demand_event`, `parking_closure`, `gate_closure` — all against the `sample` campus.

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

Prediction, optimization/routing beyond shortest-path, admin authentication, and production deployment are intentionally deferred to later modules. Real VIT-AP GPS survey data (Module 1B), real field-collected manual counts (Module 2), a real PKLot/CNRPark-EXT training run, and a real VIT-AP `cv_calibration_reports` row (Module 5) all require physical fieldwork or large external downloads that haven't happened in this environment — the tooling for all of them is built and tested against synthetic/sample stand-ins, clearly labeled as such. No accuracy or real-world benefit is claimed beyond what's actually been measured.

Module 6's frontend was verified by building it (`tsc` + `vite build`, both clean), linting it, and exercising every API call it makes against a live backend instance with `vitap.yaml` loaded (see the commit history) — but it has not been opened in an actual browser in this environment, so in-browser interaction (map rendering, click targets, geolocation prompts) hasn't had visual/manual QA.