# Field survey checklist — Module 2

This is the checklist a survey team follows when physically visiting a
parking lot or gate. It runs the same week as Module 1B's GPS walk (the
two can often be done on the same walk-through).

For a printable, non-technical one-page version, see
[`FIELD_SURVEY_ONE_PAGER.md`](FIELD_SURVEY_ONE_PAGER.md).

## Per-lot capacity count (do this once per lot, before regular collection starts)

1. Walk the entire lot. Do not estimate from one end or from a photo.
2. Count **painted parking spaces**, not vehicles — capacity is a property
   of the lot, not of how full it happens to be right now.
3. If sections are physically blocked off, reserved, or otherwise not
   usable by the general public, count them separately:
   - `usable_capacity` — spaces anyone can park in right now.
   - `reserved_capacity` — reserved for staff/specific vehicles.
   - `restricted_capacity` — off-limits (no-parking zones repainted,
     under repair, etc).
   - `temporarily_unavailable_capacity` — blocked today only (event setup,
     construction), likely to change.
   - `total_capacity` — the sum of all of the above.
4. Record the count directly into the parking capacity worksheet — do not
   round or "call it about 40."
5. Note anything ambiguous (a faded line, a space that's half in/half out
   of another zone) in `notes` rather than silently deciding for the
   observer who'll read it later.

## Candidate camera vantage point (for Module 5, later)

While you're at the lot, identify **one** vantage point that would let a
fixed camera see as much of the lot as possible:

- Prefer an elevated position (a building ledge, a light pole base, an
  existing CCTV mount) over ground level.
- Note what it can and can't see (e.g. "covers rows A–C, row D is
  occluded by the tree near the entrance").
- Take a reference photo from that exact spot if possible, and note the
  GPS point (see Module 1B) so it can be found again.
- This is a candidate, not an installation — no camera is being placed as
  part of this module.

## Regular 5-minute observation sessions

Once capacity is established, observers record occupancy at a 5-minute
cadence using the CSV templates in `data/templates/`:

- `parking_observations_template.csv` — one row per lot per 5-minute mark.
  `occupied_spaces` is a count of actually-occupied spaces at that moment,
  not a guess. `source_label` is always `REAL` for these sheets (a human
  physically counted this).
- `gates_observations_template.csv` — one row per gate per 5-minute mark:
  vehicles entered and exited since the last mark, and an optional queue
  length estimate (mark this deliberately as an estimate in `notes` if
  it's rough).
- `events_observations_template.csv` — anything unusual happening on
  campus at the time (move-in day, an exam, a cultural event) with a
  rough intensity 0 (none) to 5 (campus-wide disruption). This gives later
  analysis a reason for anomalies in the occupancy data, not a demand
  prediction.

Every row needs a `collection_session` value (see
`scripts/generate_schedule.py`) so multiple observers' sheets for the same
slot can be matched up and merged later.

## Ground-truth double-observation rule

At least one session per **priority** lot must be counted by two
observers independently and simultaneously, without comparing notes
during the count. This isn't redundancy for its own sake — it establishes
how much two careful humans naturally disagree when counting the same lot
at the same moment. That number becomes the floor Module 5's camera/CV
system is judged against: if the CV system disagrees with ground truth by
more than humans disagree with each other, that's a real accuracy problem,
not noise.

`scripts/generate_schedule.py` marks these sessions in the roster it
generates; `scripts/merge_observations.py` is what turns two observers'
independent sheets for the same session into either a confirmed
consensus row or a flagged conflict for a human to resolve — see that
script's docstring for how it decides which is which.

## After the session

Hand your CSV sheet in as-is (don't "clean it up" first — corrections
belong in `notes`, not as edits to what you actually observed). It gets
merged with any other observers' sheets for the same session by
`scripts/merge_observations.py`, which flags any disagreement between
sheets for a human to look at rather than silently picking one.
