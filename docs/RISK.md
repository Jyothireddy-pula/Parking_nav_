# Risk Engine — Module 10

Converts Module 3's current state and Module 9's predictions into danger
levels. Never decides what to do about them — no allocation, no routing,
no notifications. That's a later module's job.

## Scoring

Every sub-risk is `score = raw_value / threshold`, banded by one shared,
documented policy (`backend/app/services/risk.py`: `_band_ratio`):

    score < 0.80  -> LOW
    score < 1.00  -> MEDIUM
    score < 1.15  -> HIGH
    score >= 1.15 -> CRITICAL

All thresholds are explicit starting policy — same shape as Module 5's CV
promotion threshold and Module 9's confidence bands — not validated
against real VIT-AP outcomes, because none exist yet.

- **Overflow risk**: Module 9's 15-min prediction upper bound, as a
  percentage of the lot's `usable_capacity`, against `OVERFLOW_THRESHOLD_PCT
  = 90.0`.
- **Gate queue risk**: the worst (max) observed queue length across the
  campus's gates, against `GATE_QUEUE_THRESHOLD = 15.0` vehicles.
- **Road congestion risk**: the worst observed `RoadState.load` across the
  campus's roads, against `ROAD_LOAD_THRESHOLD = 0.8`.
- **Search risk**: this lot's *current* occupancy (not predicted), damped
  by how many other open lots on the campus currently have room —
  `current_occupancy_pct / (1 + alternatives_with_room)` — against
  `SEARCH_RISK_THRESHOLD_PCT = 70.0`. Uses current state only, so it stays
  available even when the prediction doesn't.
- **Combined network risk**: a weighted average of whichever of the above
  four are actually available (`NETWORK_RISK_WEIGHTS`: overflow 0.4,
  the rest 0.2 each), renormalized over just the available ones. Which
  dimensions were excluded, and why, is always reported
  (`excluded_from_combined`) — never silently dropped.

**Deliberate, documented simplification**: gate queue and road congestion
risk are campus-wide, not specific to whichever gate/road actually serves
this lot. Module 1's config never associates a specific gate with a
specific lot, and no module has ever written real road telemetry
(`DigitalTwinService.update_road` has zero callers in this codebase today)
— so road congestion risk reports `UNKNOWN` in every real run until a
future module starts collecting it.

## Unavailable / stale prediction — flagged, never defaulted

If Module 9's prediction has confidence `DATA_STALE` or
`INTELLIGENCE_UNAVAILABLE` (or is missing entirely), `overflow_risk` and
the proactive trigger are `available: false`, `level: "UNKNOWN"`, with an
explicit `reason` naming why — never silently scored as if data were fine.
`gate_queue_risk`/`road_congestion_risk`/`search_risk` are scored
independently of the prediction and stay available on their own terms.

## Proactive trigger

`RiskEngine.is_proactive_trigger(session, campus_id, lot_id)` fires the
instant the *predicted* occupancy crosses `OVERFLOW_THRESHOLD_PCT`, even
while current occupancy hasn't. Tested against the spec's exact example:
current 72%, 15-min prediction 94%±3% (upper bound 97%), threshold 90% —
fires now.

## API

    GET /api/v1/risk/{lot_id}?campus_id=<campus_id>

Every module in this repo scopes routes by `campus_id` (`lot_id` alone
isn't globally unique), so this follows that convention with `campus_id`
as a required query parameter rather than inventing an unscoped route.
Returns full numbers for every dimension (`raw_value`, `threshold`,
`score`, `level`, `reason`), not just a label — see
`backend/app/schemas/risk.py`.

```powershell
cd backend
pytest tests/test_risk.py tests/test_risk_routes.py
```
