"""Provenance labels for static Module 1 campus-config entities (gates,
roads, parking lots, destinations, events) — distinct from Module 3/4's
live-observation provenance labels in app.models.twin/ingestion.

- REAL: verified by Module 1B's GPS walk + satellite check, or Module 2's
  physical count. The only label that can back a capacity number.
- EXTERNAL_MAP_REFERENCE: pulled from a public map source (OpenStreetMap
  via Overpass). A real, named, real-coordinate reference — but not
  field-verified, and never a source for capacity. See docs/DATA.md.
- SAMPLE: a fabricated development/test placeholder.

SYNTHETIC and COUNTERFACTUAL (see app.models.twin) describe live
observations/simulation runs, not static entity identity or geometry, so
they aren't valid here.
"""

CONFIG_PROVENANCE_LABELS = ("REAL", "EXTERNAL_MAP_REFERENCE", "SAMPLE")
