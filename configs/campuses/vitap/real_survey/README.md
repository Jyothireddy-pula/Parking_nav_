# VIT-AP real survey — status

**The physical GPS walk survey has not been conducted yet.** This
directory is the destination for that survey's output, scaffolded ahead
of time so the workflow is clear, but it intentionally contains no
VIT-AP coordinates, road geometry, or capacity data — per this project's
rule against inventing or estimating VIT-AP data, nothing goes here until
someone has actually walked the campus with a GPS device and verified the
result against a satellite view.

## What goes here, once the walk happens

```
real_survey/
├── raw_exports/          # GPX tracks + waypoint CSVs, exactly as exported
│                         # from the device/app — never edited after capture
├── osm_reference/        # Any Overpass/OSM GeoJSON export used as a Step 1
│                         # starting skeleton (EXTERNAL_MAP_REFERENCE only)
├── vitap.generated.yaml  # Output of scripts/gps_survey_to_config.py
└── SURVEY_LOG.md         # Who walked what, when, with what device
```

## How to fill this in

1. Follow Steps 1–3 in [`docs/DATA.md`](../../../docs/DATA.md): check OSM
   first, walk the campus with GPS tracking on, verify every point against
   satellite view.
2. Drop the raw GPX/CSV exports into `raw_exports/`, unmodified.
3. Run `backend/scripts/gps_survey_to_config.py` against them to produce
   `vitap.generated.yaml`.
4. Fill in `SURVEY_LOG.md` with the actual walk details.
5. Load the generated config with `backend/scripts/load_campus_config.py`
   once it passes review.

See `backend/tests/fixtures/sample_survey.gpx` and
`sample_waypoints.csv` for a worked (fabricated, `SAMPLE`-labeled)
example of the input format the converter script expects.
