# Multi-Objective Optimization — Module 11

The project's core research contribution: given a vehicle at a gate,
`OptimizationEngine.recommend()` (`backend/app/services/optimization.py`)
picks a parking lot by minimizing a weighted, normalized objective over
risk-adjusted PREDICTED state:

    J = w1*WaitingTime + w2*QueueCost + w3*SearchTravel
      + w4*UtilizationImbalance + w5*OverflowPenalty

## Terms

Every term is normalized to `[0, 1]` by dividing its raw value by the max
raw value across this call's *feasible* candidates (`1.0` if that max is
`0`) — a simple, explicitly documented normalization scheme, not a
statistically validated one.

- **WaitingTime**: the gate's queue length (or `queue / throughput` in
  minutes, when a measured throughput exists — it almost never does, see
  `docs/RISK.md`'s road-load caveat, same situation here). Identical
  across every candidate in one call, since queueing to enter the campus
  doesn't depend on which lot you're then routed to — it still matters
  when comparing different calls/profiles, just not for ranking *within*
  one call.
- **QueueCost**: Module 10's `overflow_risk.score` for the lot (falls back
  to `predicted_occupancy_pct / 100` if Module 10 itself couldn't score
  it) — the risk of having to wait/circle for a space once at the lot.
- **SearchTravel**: Module 6's real drive-time from gate to lot.
- **UtilizationImbalance**: `|this lot's predicted occupancy − the
  average predicted occupancy across this call's candidates| / 100` — a
  load-balancing term.
- **OverflowPenalty**: `max(0, predicted_occupancy_pct − 100) / 100` —
  zero unless a candidate is predicted to exceed capacity outright.

## Profiles

| Profile | w1 (Wait) | w2 (Queue) | w3 (Search) | w4 (Imbalance) | w5 (Overflow) |
|---|---|---|---|---|---|
| **P1** Minimum Waiting | 0.40 | 0.15 | 0.35 | 0.05 | 0.05 |
| **P2** Balanced (default) | 0.20 | 0.20 | 0.20 | 0.20 | 0.20 |
| **P3** Maximum Utilization | 0.05 | 0.15 | 0.05 | 0.35 | 0.40 |

## Feasibility — rejected before scoring, always

`_generate_candidates` rejects, for every lot, before any objective term
is ever computed: a closed gate, a closed or restricted lot, a lot with
zero currently-available capacity ("full"), and any lot Module 6's
`find_route` can't reach (a closed gate/lot/road along every path — reused
directly from Module 6 rather than re-implemented). A cheaper-looking
infeasible candidate is structurally impossible to return: `recommend()`
only ever calls `min()` over the `feasible` list, never the full candidate
list. No feasible candidate at all returns a normal result
(`feasible=False`, an explicit `reason`) — never an exception.

## Failure handling

- **Prediction unavailable or stale**: `_predicted_occupancy_pct` falls
  back to `_historical_average_fallback` — a live mean of that lot's own
  recent real observations (not Module 9's trained pipeline, which may be
  exactly what's unavailable) — and, if that also has nothing, to the
  lot's current occupancy. Every candidate's `prediction_source` records
  which of `model` / `historical_average_fallback` / `current_state_fallback`
  was actually used.
- **Time limit exceeded** (`TIME_LIMIT_SECONDS = 2.0`, checked between
  candidates while scoring): aborts and falls back to nearest-available
  among the already-gathered feasible candidates, flagged
  `used_fallback="time_limit_exceeded"`.
- **Determinism**: candidates are always considered in `lot_id` order,
  ties broken by `lot_id`. J values are compared for ranking with a
  `J_TOLERANCE = 1e-9` — ranking is stable and deterministic for identical
  inputs, but exact floating-point J values may differ in their last few
  decimal digits across platforms/BLAS versions; this is not a promise of
  bit-identical output.

## B1/B2/B3 + the optimizer — four comparison strategies

`recommend_baseline(strategy=...)` shares the exact same feasibility
filter as the real optimizer (an infeasible candidate is never returned by
these either):

- **B1** `first_available`: the feasible candidate with the lowest `lot_id`.
- **B2** `nearest_available`: the feasible candidate with the shortest
  travel time.
- **B3** `prediction_only`: the feasible candidate with the lowest
  Module-9-predicted occupancy — **fully implemented against Module 9's
  real `PredictionService`**, not a stub. (Module 8's own
  `PredictionOnlyStrategy` in `backend/app/services/allocation.py` stays a
  stand-in permanently for a different reason: it's called synchronously,
  once per vehicle, inside Module 7's simulation loop with no DB session
  and no trained model behind synthetic scenario data nothing ever
  observed — there's no real prediction signal available to swap in
  there. Module 11's B3 is the real one, for the live system.)

`compare()` runs all four (B1, B2, B3, and `recommend()` itself) against
the same live moment — a single-shot comparison, not Module 8's
`ExperimentRunner` (which compares many *simulated* scenario runs; this
compares one real recommendation, so it doesn't reuse that framework).

## Report note

There is no `POST /recommend` API route — following the same precedent as
Module 7 (whose spec also omitted an "API:" line and shipped as a
service+CLI/tests module, not a REST endpoint). Module 11 is
service-layer + tests; exposing it over REST is left to whichever future
module actually calls it to act on a recommendation.

```powershell
cd backend
pytest tests/test_optimization.py
```
