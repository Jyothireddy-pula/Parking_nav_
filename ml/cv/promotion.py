"""The cv_auto / cv_verified promotion rule (Module 5, item 4).

This is a documented policy decision, not an assumption: a lot's CV
readings are only trusted unsupervised (collection_method=cv_auto) once
its measured calibration error against Module 2's manual ground truth is
below this threshold. Until then, every CV reading for that lot is
labeled cv_verified — meaning it still needs a human spot-check before
being treated as authoritative.
"""

CV_AUTO_PROMOTION_THRESHOLD_FRACTION = 0.10  # MAE must be < 10% of the lot's total_capacity

CV_AUTO = "cv_auto"
CV_VERIFIED = "cv_verified"


def decide_collection_method(mae: float, total_capacity: int) -> str:
    """mae: mean absolute error (in spaces) from a cv_calibration_reports
    row for this lot. total_capacity: the lot's Module 1 total_capacity."""

    if total_capacity <= 0:
        raise ValueError(f"total_capacity must be > 0, got {total_capacity}")
    if mae < 0:
        raise ValueError(f"mae must be >= 0, got {mae}")

    threshold = CV_AUTO_PROMOTION_THRESHOLD_FRACTION * total_capacity
    return CV_AUTO if mae < threshold else CV_VERIFIED
