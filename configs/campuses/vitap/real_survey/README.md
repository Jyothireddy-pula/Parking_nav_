# VIT-AP real survey — status

**Step 1 (OSM check) is done — see `osm_reference/` and
`vitap_candidate.yaml`.** Steps 2–3 (the physical GPS walk and
satellite verification) have not happened yet. Per this project's rule
against inventing or estimating VIT-AP data, nothing here is labeled
`REAL` until someone has actually walked the campus with a GPS device
and verified the result against a satellite view.

## Structure

```
real_survey/
├── raw_exports/          # GPX tracks + waypoint CSVs, exactly as exported
│                         # from the device/app — never edited after capture
│                         # (empty — Step 2 hasn't happened yet)
├── osm_reference/        # DONE: Overpass/OSM GeoJSON pull, EXTERNAL_MAP_REFERENCE
│                         # only — see osm_reference/README.md for what's in it
├── vitap_candidate.yaml  # DONE: the 11 real named buildings from osm_reference/,
│                         # in Module 1's schema shape — NOT loadable yet, see below
├── vitap.generated.yaml  # Output of scripts/gps_survey_to_config.py (not yet generated)
└── SURVEY_LOG.md         # Who walked what, when, with what device (no entries yet)
```

## `vitap_candidate.yaml` — real data, correctly not usable yet

This is real: 11 building names and coordinates, pulled live from
OpenStreetMap, in the exact shape Module 1's config expects, each
stamped `provenance: EXTERNAL_MAP_REFERENCE`. It has **no gates, no
parking lots, and no roads** — OSM has zero gates and zero
name/capacity-bearing parking lots for this campus, and while ~100
roads/paths exist in the OSM pull, none reliably connect two of these
buildings without inventing adjacency (see `osm_reference/README.md`
for the one weak candidate that was found and rejected).

`backend/tests/test_vitap_candidate_config.py` proves this state
concretely: every entity in the file parses correctly (real names, real
coordinates, valid categories), but loading the file for real correctly
fails Module 1's orphan-node check — all 11 destinations are flagged,
because nothing connects them yet. That failure is the honest, current
status, not a bug: real names and coordinates exist, but the campus
isn't walkable, connected, or capacitied yet. Nothing was forced through
to make this "work" — the physical walk is what's actually missing.

## How to finish this

1. ~~Check OSM first (Step 1)~~ — done, see `osm_reference/README.md`
   and `vitap_candidate.yaml`.
2. Walk the campus with GPS tracking on, verify every point against
   satellite view (Steps 2–3, `docs/DATA.md`). Real head start: 11
   buildings already have names and rough locations to confirm/correct
   (AB-1, AB-2, CB, MH-1/2/3/6/7, LH-1, Food Street, MH-2 Food Store),
   ~100 roads/paths are roughly mapped, and 2 unnamed parking areas have
   outlines. Still needed from scratch: every gate, every lot's capacity
   count, and enough walked roads to actually connect the buildings.
3. Drop the raw GPX/CSV exports into `raw_exports/`, unmodified.
4. Run `backend/scripts/gps_survey_to_config.py` against them to produce
   `vitap.generated.yaml` — this can reuse the 11 real names/categories
   above (re-verified on the walk) plus whatever `vitap_candidate.yaml`
   didn't have.
5. Fill in `SURVEY_LOG.md` with the actual walk details.
6. Load the generated config with `backend/scripts/load_campus_config.py`
   once it passes review.

See `backend/tests/fixtures/sample_survey.gpx` and
`sample_waypoints.csv` for a worked (fabricated, `SAMPLE`-labeled)
example of the input format the converter script expects.
