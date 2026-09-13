# VIT-AP real survey — status

**Step 1 (OSM check) is done, and the campus is now loadable** as
`../../vitap.yaml` (`configs/campuses/vitap.yaml`, one level up from
here) — see that file's own header. Steps 2–3 (the physical GPS walk
and satellite verification) have not happened yet. Per this project's
rule against inventing or estimating VIT-AP data, nothing here is
labeled `REAL` until someone has actually walked the campus with a GPS
device and verified the result against a satellite view.

## Structure

```
real_survey/
├── raw_exports/          # GPX tracks + waypoint CSVs, exactly as exported
│                         # from the device/app — never edited after capture
│                         # (empty — Step 2 hasn't happened yet)
├── osm_reference/        # DONE: Overpass/OSM GeoJSON pull, EXTERNAL_MAP_REFERENCE
│                         # only — see osm_reference/README.md for what's in it
├── vitap_candidate.yaml  # DONE: the 11 real named buildings, EXTERNAL_MAP_REFERENCE
│                         # only — kept as a record of exactly what's real
├── vitap.generated.yaml  # Output of scripts/gps_survey_to_config.py (not yet generated)
└── SURVEY_LOG.md         # Who walked what, when, with what device (no entries yet)

../vitap.yaml             # ACTIVE, LOADABLE: the 11 real destinations above, plus a
                          # fabricated SAMPLE gate/lot/roads for connectivity — see
                          # its header before treating any of it as real infrastructure
```

## Two files, two purposes

- **`vitap_candidate.yaml`** (this directory): the honest record of
  exactly what Step 1 found — 11 real destinations, nothing else. It's
  intentionally *not* loadable (`backend/tests/test_vitap_candidate_config.py`
  proves it correctly fails Module 1's orphan-node check, since no
  gate/lot/road exists in real data). Keep this file as the reference
  for "what did OSM actually give us."
- **`../vitap.yaml`**: the active campus config the system actually
  loads. Same 11 real destinations, `EXTERNAL_MAP_REFERENCE`. Plus a
  fabricated placeholder gate, parking lot, and a straight-line road
  from the lot to every destination — all stamped `provenance: SAMPLE`,
  added only so the campus is loadable/routable/twin-able for
  development before the physical walk happens
  (`backend/tests/test_vitap_config.py` verifies the real/fake split
  stays exactly this way). None of the `SAMPLE` entities are real
  infrastructure — no confirmed gate, no surveyed lot capacity, no
  walked road exists yet.

## How to finish this for real

1. ~~Check OSM first (Step 1)~~ — done, see `osm_reference/README.md`
   and `vitap_candidate.yaml`.
2. Walk the campus with GPS tracking on, verify every point against
   satellite view (Steps 2–3, `docs/DATA.md`). Real head start: 11
   buildings already have names and rough locations to confirm/correct
   (AB-1, AB-2, CB, MH-1/2/3/6/7, LH-1, Food Street, MH-2 Food Store),
   ~100 roads/paths are roughly mapped, and 2 unnamed parking areas have
   outlines. Still needed from scratch: every gate, every lot's capacity
   count, and every real walked road (replacing `vitap.yaml`'s
   straight-line placeholders one by one).
3. Drop the raw GPX/CSV exports into `raw_exports/`, unmodified.
4. Run `backend/scripts/gps_survey_to_config.py` against them to produce
   `vitap.generated.yaml` — this can reuse the 11 real names/categories
   above (re-verified on the walk).
5. Fill in `SURVEY_LOG.md` with the actual walk details.
6. Merge the real gate/lot/roads into `../vitap.yaml`, removing the
   `SAMPLE` placeholders they replace, and flip each destination's
   `provenance` to `REAL` once its coordinate has been walked and
   satellite-checked. Load with `backend/scripts/load_campus_config.py`
   once it passes review.

See `backend/tests/fixtures/sample_survey.gpx` and
`sample_waypoints.csv` for a worked (fabricated, `SAMPLE`-labeled)
example of the input format the converter script expects.
