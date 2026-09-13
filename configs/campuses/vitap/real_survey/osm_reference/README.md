# VIT-AP OSM reference (Module 1B, Step 1 — DONE)

This is real data, pulled live from the public Overpass API on 2026-09-13.
It is a **starting skeleton only** — every name, shape, and boundary here
is `EXTERNAL_MAP_REFERENCE` and stays that way until a physical GPS walk
(Step 2) and satellite-view check (Step 3) verify it. Nothing here has
been through that verification yet, so nothing here is `REAL`, and none
of it has been copied into `configs/campuses/vitap.yaml` (no such file
exists yet).

## What was queried

```
# Campus boundary (found via web search -> OSM way 750542244)
https://overpass-api.de/api/interpreter
  data=[out:json];way(750542244);(._;>;);out body;

# Everything tagged building/highway/parking/gate inside that boundary's
# bounding box (16.4905,80.4940 to 16.4975,80.5022)
https://overpass-api.de/api/interpreter
  data=[out:json][timeout:25];
    (
      way["building"](16.4905,80.4940,16.4975,80.5022);
      way["highway"](16.4905,80.4940,16.4975,80.5022);
      way["amenity"="parking"](16.4905,80.4940,16.4975,80.5022);
      node["barrier"="gate"](16.4905,80.4940,16.4975,80.5022);
      node["amenity"="parking"](16.4905,80.4940,16.4975,80.5022);
    );
    out body; >; out skel qt;
```

## Files

- `overpass_campus_boundary.json` — raw response for the campus boundary way, unmodified.
- `overpass_raw_response.json` — raw response for the bbox feature query, unmodified.
- `vitap_osm_skeleton.geojson` — both merged and converted to GeoJSON via
  `backend/scripts/overpass_export_to_geojson.py`. Every feature carries
  `"provenance": "EXTERNAL_MAP_REFERENCE"`.

## What's actually in it

- 1 campus boundary polygon (`amenity=university`, "VIT-AP University").
- 40 tagged buildings, including named ones: `AB-1`, `AB-2` (academic
  blocks), `CB` (central block), `MH-1`, `MH-2`, `MH-3`, `MH-6`, `MH-7`
  (men's hostels), `LH-1` (ladies' hostel), `Food Street`, `MH-2 Food
  Store`. The other ~29 buildings are untagged (`building=yes`, no name).
- ~100 road/path ways: mostly `footway` (51) and `service` roads (34),
  plus a handful of `corridor`, `track`, `tertiary`, `unclassified`, and
  one under `construction`.
- 2 parking-area outlines (untagged beyond `amenity=parking` — no name,
  no capacity; **capacity must never be estimated from these shapes**,
  per project rules — it can only come from Module 2's physical count).
- **0 gates.** No `barrier=gate` nodes exist in OSM for this campus.
  Gates need to be captured entirely fresh during the GPS walk (Step 2).

## What this does and doesn't unblock

**Does**: gives Module 1B's Step 2 walkers a real starting reference —
which buildings already have OSM names to confirm/correct, roughly where
the ~100 paths run, and where the 2 known parking areas are, so the walk
can be planned instead of starting from nothing.

**Doesn't**: this is not survey-grade, has no capacity data, has no
gates, and about 29 of 40 buildings have no name at all in OSM. It does
not reduce the need for Steps 2–3, and no coordinate from this file may
be typed into a real config without that verification.
