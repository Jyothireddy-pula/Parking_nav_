# VIT-AP real survey — status

**Step 1 (OSM check) is done — see `osm_reference/`.** Steps 2–3 (the
physical GPS walk and satellite verification) have not happened yet.
This directory intentionally still contains no VIT-AP coordinates,
road geometry, or capacity data beyond `osm_reference/`'s
`EXTERNAL_MAP_REFERENCE`-labeled OSM pull — per this project's rule
against inventing or estimating VIT-AP data, nothing becomes `REAL`
until someone has actually walked the campus with a GPS device and
verified the result against a satellite view.

## Structure

```
real_survey/
├── raw_exports/          # GPX tracks + waypoint CSVs, exactly as exported
│                         # from the device/app — never edited after capture
│                         # (empty — Step 2 hasn't happened yet)
├── osm_reference/        # DONE: Overpass/OSM GeoJSON pull, EXTERNAL_MAP_REFERENCE
│                         # only — see osm_reference/README.md for what's in it
├── vitap.generated.yaml  # Output of scripts/gps_survey_to_config.py (not yet generated)
└── SURVEY_LOG.md         # Who walked what, when, with what device (no entries yet)
```

## How to finish this

1. ~~Check OSM first (Step 1)~~ — done, see `osm_reference/README.md`.
2. Walk the campus with GPS tracking on, verify every point against
   satellite view (Steps 2–3, `docs/DATA.md`). The OSM pull gives you a
   real head start: 40 buildings already have rough locations (11 named:
   AB-1, AB-2, CB, MH-1/2/3/6/7, LH-1, Food Street), ~100 roads/paths are
   roughly mapped, and 2 parking areas have outlines — but it has **zero
   gates** and no capacity data, so those still need to be captured from
   scratch, and every OSM point still needs on-the-ground correction.
3. Drop the raw GPX/CSV exports into `raw_exports/`, unmodified.
4. Run `backend/scripts/gps_survey_to_config.py` against them to produce
   `vitap.generated.yaml`.
5. Fill in `SURVEY_LOG.md` with the actual walk details.
6. Load the generated config with `backend/scripts/load_campus_config.py`
   once it passes review.

See `backend/tests/fixtures/sample_survey.gpx` and
`sample_waypoints.csv` for a worked (fabricated, `SAMPLE`-labeled)
example of the input format the converter script expects.
