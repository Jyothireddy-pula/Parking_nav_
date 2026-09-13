# Computer Vision Occupancy Detection — Module 5

Goal: after Module 2's manual counting has run for a couple of weeks,
automate it — but only ever claim an accuracy this system actually
measured, and only promote a lot to unsupervised automatic counting once
that measurement clears an explicit bar.

## 1. Training data — PKLot / CNRPark-EXT (EXTERNAL, permanently)

Verified current download locations (checked via web search at the time
of writing this module — re-verify before a real training run, as these
can move):

- **PKLot**: `http://www.inf.ufpr.br/vri/databases/PKLot.tar.gz` — ~700k
  labeled parking-space crops from UFPR/PUCPR (Curitiba, Brazil), three
  weather conditions, XML polygon annotations per image.
  ([source](https://www.inf.ufpr.br/lesoliveira/download/pklot-readme.pdf))
- **CNRPark-EXT**: `http://cnrpark.it/dataset/CNR-EXT-Patches-150x150.zip`
  — ~150k labeled patches from a car park in Italy, several weather/angle
  conditions. ([source](https://github.com/fabiocarrara/deep-parking/issues/2))

**Labeling rule, permanent, no exceptions**: any model trained on either
of these is trained on data labeled `EXTERNAL`. That label never changes,
even after the model ships. External data can teach a classifier what an
occupied vs. vacant parking space generally looks like; it cannot prove
the model is accurate for VIT-AP's cameras, angles, lighting, or lot
layouts. Only Module 5's calibration report (§3) can say anything about
VIT-AP accuracy, and only once real VIT-AP footage and Module 2's manual
counts both exist.

**What was actually run in this session**: this environment has no GPU
and no budget to download and train on ~700k/~150k real images, so no
real PKLot/CNRPark-EXT training run happened here. `ml/cv/train_classifier.py`,
`ml/cv/dataset.py`, and `ml/cv/classifier.py` are built and tested end to
end against a small SYNTHETIC generated stand-in (`ml/tests/conftest.py`)
so the code path is proven to work — but the accuracy numbers that
produces describe the synthetic set, not PKLot/CNRPark-EXT, and are never
presented as such. Running the real thing is documented in §6.

## 2. Model

A logistic regression over three handcrafted features per space crop
(`ml/cv/features.py`): mean intensity, intensity std-dev, and mean Sobel
edge magnitude. Not a CNN — this project has no verified GPU training
run to back one, and a small inspectable baseline is what's actually
built and tested here. The interface (`extract_features` in, label +
confidence out) is designed so a CNN can later replace just that one
function without touching the rest of the pipeline.

## 3. Per-lot space polygons

`ml/cv/annotate_spaces.py` — a human clicks each space's corners on one
reference photo per lot (`main()`, interactive, not unit-tested); the
data model (`SpacePolygon`/`LotAnnotation`), JSON save/load, and
bounding-box crop extraction are pure functions and are tested. Each
space needs 3+ points; a lot's annotation lists every space with a
stable `space_id` matching the physical space Module 2 counts by hand.

## 4. Calibration against Module 2's ground truth

`backend/app/services/cv_calibration.py` pairs, for one lot,
`manual_count` observations against `cv_auto`/`cv_verified` observations
at the **same timestamp** (both come from Module 4's `observations`
table) and computes:

    MAE = mean(|manual_count - cv_count|)  over all paired timestamps

stored in `cv_calibration_reports` (`campus_id`, `parking_lot_id`,
`sample_size`, `mae`, `recommended_collection_method`, `timestamp`).
`sample_size` is how many paired timestamps went into that MAE — this
number matters: an MAE from 3 pairs is far less trustworthy than one from
30, even if the number itself looks the same.

## 5. Promotion rule (explicit policy, not an assumption)

`ml/cv/promotion.py` (canonical) / `backend/app/services/cv_calibration.py`
(mirrored constant, kept in sync by a test that asserts equality):

    threshold = 10% of the lot's total_capacity
    mae <  threshold  ->  cv_auto       (unsupervised, trusted)
    mae >= threshold  ->  cv_verified   (still needs a human spot-check)

This is a documented starting threshold, not a validated one — it has
not been tuned against real VIT-AP calibration data because none exists
yet (see §6). Revisit it once real calibration reports exist.

## 6. Pipeline

`ml/cv/pipeline.py`: frame → per-space crop (via the lot's polygons) →
classify → aggregate → POST to Module 4's `/observations/cv-batch`, with
`source_label=REAL` (a real camera really observed this lot — "REAL"
describes provenance, not classifier correctness) and
`collection_method` taken from that lot's current promotion-rule
decision. `CVPipeline.run_forever` loops on a configurable interval; a
real deployment wires `frame_source` to an actual camera/RTSP feed.

**Low-confidence handling**: before classifying anything, a frame's blur
is checked (variance of Laplacian, `ml/cv/blur.py`); a blurry/occluded
frame is flagged `low_confidence` and nothing is posted for it. Even a
sharp frame can still be flagged `low_confidence` if too many individual
spaces come back below the confidence threshold (default 65%, more than
20% of spaces uncertain). A low-confidence frame is logged and skipped —
never posted as a best-guess count. Module 2's manual counts continue to
cover a lot until real conditions (and a real calibration report) justify
trusting its camera.

## Report

**External-data (PKLot/CNRPark-EXT) accuracy**: not measured in this
session — no real download/training run happened here (see §1). Anyone
running `ml/cv/train_classifier.py` against the real datasets at the
locations above will get a real, printed accuracy number for that run;
until that happens, no number is claimed. As a sanity check that the
code itself works, the classifier reaches ≥85% held-out accuracy on the
SYNTHETIC generated set the test suite creates (`ml/tests/test_classifier.py`,
`ml/tests/test_train_classifier.py`) — a code-correctness signal, not an
external-dataset accuracy claim.

**VIT-AP calibration error**: not measured — no VIT-AP camera footage and
no Module 2 manual ground-truth counts exist yet (Module 1B's physical
survey and Module 2's field survey are both still pending real-world
execution; see their own docs). `cv_calibration_reports` and the
`decide_collection_method` promotion logic are built and tested against
synthetic paired data; the first real row in that table only appears
once real footage and real manual counts both exist for the same lot and
timestamp.

**Recommended ongoing manual spot-check frequency**: until a lot has a
`cv_calibration_report` with `sample_size >= 20` and `recommended_collection_method
== cv_auto`, keep every reading `cv_verified` and have a human spot-check
at least one reading per lot per day (ideally at a different time of day
each day, to catch lighting/weather conditions the calibration sample
might have missed). After a lot is promoted to `cv_auto`, drop to one
spot-check per lot per week, and re-run calibration (a fresh
`cv_calibration_reports` row) monthly or after any camera/angle change —
a promoted lot is not promoted forever without re-checking.
