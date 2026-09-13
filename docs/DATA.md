# Data provenance and GPS survey methodology

This document covers Module 1B (map acquisition) and how it feeds Module 1
(campus configuration). It exists so anyone can answer "how do we know this
coordinate is real?" for any point in the system.

## Provenance labels

Every stored value carries exactly one of:

- `REAL` — a verified VIT-AP observation (GPS survey point, manual count, or CV).
- `EXTERNAL_MAP_REFERENCE` — pulled from a public map source (OpenStreetMap via
  Overpass) as an unverified starting skeleton. Never merged into VIT-AP's
  `REAL` dataset without independent verification (Step 3 below).
- `EXTERNAL` — a public dataset (PKLot/CNRPark/Birmingham) used for model
  training only, never merged into VIT-AP's operational data.
- `SYNTHETIC` — simulator output.
- `SAMPLE` — a fabricated development/test placeholder (e.g. the `sample`
  campus in `configs/campuses/sample.yaml`, and the fixtures under
  `backend/tests/fixtures/`). Never presented as real.
- `COUNTERFACTUAL` — a simulation replay of real historical data.

A missing observation is `MISSING`, never zero, never interpolated.

## Step 1 — OpenStreetMap as a starting skeleton (EXTERNAL_MAP_REFERENCE)

Before any physical walk, check whether VIT-AP's buildings, roads, and
parking areas are already mapped:

1. Open [overpass-turbo.eu](https://overpass-turbo.eu) (free, no signup).
2. Query the VIT-AP campus bounding box for `building`, `highway`, `amenity=parking`,
   and `barrier=gate` tags.
3. Export any hits as GeoJSON.

This is a **starting skeleton only**. OSM coverage for VIT-AP may be
outdated, missing, or wrong (mislabeled buildings, roads that no longer
exist, capacities that were never accurate to begin with). Anything taken
from this source is labeled `EXTERNAL_MAP_REFERENCE` and must be
independently verified in Step 3 before it can become `REAL`.

**Status: done.** Queried live against the public Overpass API (no
signup needed, no overpass-turbo.eu UI required — a direct HTTP query
works the same way) on 2026-09-13. Found real coverage: a campus
boundary, 40 tagged buildings (11 named — academic blocks, hostels,
a central block, a food street), ~100 road/path ways, and 2 parking-area
outlines. Zero gates. Raw responses and the converted GeoJSON are in
`configs/campuses/vitap/real_survey/osm_reference/` — see that
directory's `README.md` for the exact queries run and a full breakdown.
`backend/scripts/overpass_export_to_geojson.py` does the JSON→GeoJSON
conversion and stamps every feature `EXTERNAL_MAP_REFERENCE`. Steps 2–3
(the physical walk and satellite verification) still haven't happened —
this skeleton does not change that requirement, it just gives the walk
something real to start from instead of nothing.

`EXTERNAL_MAP_REFERENCE` is now an enforced Module 1 schema value, not
just a documentation convention: every gate, road, and destination
carries a required `provenance` field (`REAL` / `EXTERNAL_MAP_REFERENCE`
/ `SAMPLE`), and parking lots specifically reject
`EXTERNAL_MAP_REFERENCE` outright — capacity can never come from a map
source, so the schema won't accept that provenance value for a lot at
all (`app/config_loader/schema.py`, `app/models/provenance.py`). The 11
real named buildings this Overpass pull found are captured as an actual
`CampusConfigFile`-shaped candidate at
`configs/campuses/vitap/real_survey/vitap_candidate.yaml` — every entity
parses correctly, but loading it for real correctly fails Module 1's
orphan-node check, because nothing connects those buildings yet. See
that directory's `README.md`.

## Step 2 — GPS walk survey (produces REAL coordinates)

Conducted the same week, the same physical walk, as Module 2's field
survey (parking lot capacity counts). Two acceptable tools:

- A GPX track-logging app, recording a continuous path while walking (not
  just dropped points) — required for roads and parking lot perimeters,
  since a straight line between two endpoints is not the real path.
- Google Maps drop-pin + copy coordinates, for single points (a gate, a
  destination entrance) where a route/perimeter is not applicable.

What to capture per entity:

| Entity | What to walk/record |
|---|---|
| Gate | One point, at the gate itself |
| Parking lot | Walk the full perimeter (GPS track, 4+ points) + one center point |
| Destination | One point, at the entrance actually used |
| Road/path | Walk it with track recording on, so the geometry follows the real curve |

### Known limitation: consumer GPS accuracy

A phone's GPS is typically accurate to **~3–5 meters** under open sky, and
worse near tall buildings, under dense tree cover, or indoors. This is
**not survey-grade precision** and this project does not claim it is. Two
consequences:

- Points near building walls, gate posts, or parking lot boundaries may be
  off by a few meters from where they visually appear on a satellite image.
- Distances/areas computed from these points inherit that error; anything
  built on top of them (routing, ETA, lot boundaries) should not be
  presented as more precise than the underlying survey.

Step 3 exists specifically to catch and correct these offsets before they
enter the config.

## Step 3 — Satellite verification

Before any captured point is written into a config file:

1. Open the same location in Google Maps' satellite layer.
2. Compare the captured point against the visible building/road/lot edge.
3. If there's an obvious offset (the point sits inside a building wall, or
   clearly off a road), correct it manually rather than accepting the bad
   fix silently. Record the correction in the survey log (see
   `SURVEY_LOG.md` template below) — never silently overwrite without a
   record of what changed and why.

Only after this step does a point become `REAL`.

## Step 4 — Converting survey data into a Module 1 config

`backend/scripts/gps_survey_to_config.py` converts a GPX file (tracks +
waypoints) and a waypoint/track mapping CSV into a Module 1 YAML config.

- Road `geometry` is taken directly from the walked GPX track, **in
  recorded order** — never reordered or straightened into a line between
  endpoints.
- Parking lot `geometry` (perimeter) likewise comes from the walked
  perimeter track; `center` comes from a separate waypoint.
- Any CSV row whose GPX reference (a waypoint or track name) is not found
  in the GPX file is **rejected**, not filled in with a guess.
- `expected_travel_time` for a road must be provided (measured during the
  walk); the script refuses to invent one.

Run it:

```powershell
cd backend
python -m scripts.gps_survey_to_config `
  --gpx path\to\survey.gpx `
  --waypoints path\to\waypoints.csv `
  --campus-id vitap `
  --campus-name "VIT-AP University" `
  --timezone Asia/Kolkata `
  --output ..\configs\campuses\vitap\real_survey\vitap.generated.yaml
```

The output config still goes through Module 1's full schema and
cross-entity validation (duplicate IDs, orphan nodes, capacity checks)
before it's usable — see `backend/app/config_loader/`.

## Where things live

- `configs/campuses/sample.yaml` — a fabricated `SAMPLE` campus for local
  development. Not real.
- `configs/campuses/vitap/real_survey/` — the real VIT-AP survey's raw
  evidence (GPX/CSV exports, kept unmodified as source-of-truth), the
  generated config, and `SURVEY_LOG.md` recording who walked what, when,
  with what device. See that directory's own README for current status —
  as of this writing, the physical walk has not yet been conducted; this
  repository only ships the tooling and the empty evidence trail waiting
  to be filled in.
