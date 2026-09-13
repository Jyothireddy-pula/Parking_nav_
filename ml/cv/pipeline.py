"""Frame -> per-space crop -> classify -> aggregate -> POST to Module 4.

Runs on a configurable interval (see CVPipeline.run_forever). Every posted
batch uses source_label=REAL (a real camera observed a real lot; "REAL"
describes the data's provenance, not the classifier's correctness) and
collection_method=cv_auto or cv_verified per the promotion rule in
promotion.py.

Low-confidence handling: a blurry/occluded frame, or a frame where too
many individual spaces classify below the confidence threshold, is
flagged low_confidence and NOTHING is posted for it. Returning a
best-guess count from an unreliable frame would be silently wrong; the
frame is logged and skipped instead — Module 2's manual counts continue
to cover for it until conditions improve.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
import numpy as np

from cv.annotate_spaces import LotAnnotation, crop_space
from cv.blur import DEFAULT_BLUR_VARIANCE_THRESHOLD, is_blurry
from cv.classifier import DEFAULT_CONFIDENCE_THRESHOLD, OCCUPIED, VACANT, OccupancyClassifier

logger = logging.getLogger(__name__)

# If more than this fraction of spaces in a frame come back low-confidence,
# the whole frame is untrustworthy even if it isn't technically "blurry."
DEFAULT_MAX_UNCERTAIN_FRACTION = 0.2


@dataclass
class SpaceResult:
    space_id: str
    label: str | None  # None if this space was uncertain
    confidence: float


@dataclass
class FrameResult:
    occupied_count: int
    vacant_count: int
    uncertain_count: int
    total_spaces: int
    low_confidence: bool
    reason: str | None = None
    spaces: list[SpaceResult] = field(default_factory=list)


def classify_frame(
    image: np.ndarray,
    annotation: LotAnnotation,
    classifier: OccupancyClassifier,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    blur_threshold: float = DEFAULT_BLUR_VARIANCE_THRESHOLD,
    max_uncertain_fraction: float = DEFAULT_MAX_UNCERTAIN_FRACTION,
) -> FrameResult:
    if is_blurry(image, blur_threshold):
        return FrameResult(
            occupied_count=0,
            vacant_count=0,
            uncertain_count=len(annotation.spaces),
            total_spaces=len(annotation.spaces),
            low_confidence=True,
            reason="frame is too blurry/occluded to classify reliably",
        )

    space_results: list[SpaceResult] = []
    for space in annotation.spaces:
        crop = crop_space(image, space)
        label, confidence = classifier.predict_one(crop)
        if confidence < confidence_threshold:
            space_results.append(SpaceResult(space_id=space.space_id, label=None, confidence=confidence))
        else:
            space_results.append(SpaceResult(space_id=space.space_id, label=label, confidence=confidence))

    occupied_count = sum(1 for s in space_results if s.label == OCCUPIED)
    vacant_count = sum(1 for s in space_results if s.label == VACANT)
    uncertain_count = sum(1 for s in space_results if s.label is None)
    total = len(space_results)

    uncertain_fraction = (uncertain_count / total) if total else 1.0
    low_confidence = uncertain_fraction > max_uncertain_fraction
    reason = (
        f"{uncertain_count}/{total} spaces were below the confidence threshold" if low_confidence else None
    )

    return FrameResult(
        occupied_count=occupied_count,
        vacant_count=vacant_count,
        uncertain_count=uncertain_count,
        total_spaces=total,
        low_confidence=low_confidence,
        reason=reason,
        spaces=space_results,
    )


def build_cv_batch_payload(
    parking_lot_id: str,
    timestamp: datetime,
    frame_result: FrameResult,
    collection_method: str,
) -> dict | None:
    """Returns the single-observation payload for Module 4's cv-batch
    endpoint, or None if the frame was low-confidence and nothing should
    be posted."""

    if frame_result.low_confidence:
        return None

    return {
        "timestamp": timestamp.isoformat(),
        "parking_lot_id": parking_lot_id,
        "occupied_spaces": frame_result.occupied_count,
        "notes": (
            f"cv pipeline: {frame_result.occupied_count} occupied, {frame_result.vacant_count} vacant, "
            f"{frame_result.uncertain_count} uncertain of {frame_result.total_spaces} spaces"
        ),
        "source_label": "REAL",
        "collection_method": collection_method,
    }


PosterFn = Callable[[str, list[dict]], Awaitable[httpx.Response]]


async def default_poster(cv_batch_url: str, payloads: list[dict]) -> httpx.Response:
    async with httpx.AsyncClient() as client:
        return await client.post(cv_batch_url, json=payloads, timeout=30.0)


@dataclass
class CVPipeline:
    campus_id: str
    backend_base_url: str
    classifier: OccupancyClassifier
    lot_annotations: dict[str, LotAnnotation]
    collection_methods: dict[str, str]  # parking_lot_id -> "cv_auto" | "cv_verified", from the promotion rule
    poster: PosterFn = default_poster
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    blur_threshold: float = DEFAULT_BLUR_VARIANCE_THRESHOLD

    def _cv_batch_url(self) -> str:
        return f"{self.backend_base_url}/api/v1/campuses/{self.campus_id}/observations/cv-batch"

    async def run_once(
        self, parking_lot_id: str, image: np.ndarray, timestamp: datetime | None = None
    ) -> FrameResult:
        annotation = self.lot_annotations.get(parking_lot_id)
        if annotation is None:
            raise KeyError(f"no space annotation loaded for parking_lot_id {parking_lot_id!r}")

        frame_result = classify_frame(
            image, annotation, self.classifier, self.confidence_threshold, self.blur_threshold
        )

        if frame_result.low_confidence:
            logger.warning(
                "cv frame skipped: low confidence",
                extra={"campus_id": self.campus_id, "parking_lot_id": parking_lot_id, "reason": frame_result.reason},
            )
            return frame_result

        collection_method = self.collection_methods.get(parking_lot_id, "cv_verified")
        payload = build_cv_batch_payload(
            parking_lot_id, timestamp or datetime.now(timezone.utc), frame_result, collection_method
        )
        response = await self.poster(self._cv_batch_url(), [payload])
        response.raise_for_status()
        return frame_result

    async def run_forever(
        self,
        frame_source: Callable[[str], Awaitable[np.ndarray]],
        interval_seconds: float,
        stop_after_iterations: int | None = None,
    ) -> None:
        """frame_source(parking_lot_id) supplies the latest frame for a
        lot — a real deployment wires this to a camera/RTSP client.
        stop_after_iterations is for tests; a real run leaves it None and
        loops until the process is stopped."""

        import asyncio

        iterations = 0
        while stop_after_iterations is None or iterations < stop_after_iterations:
            for parking_lot_id in self.lot_annotations:
                image = await frame_source(parking_lot_id)
                await self.run_once(parking_lot_id, image)
            iterations += 1
            if stop_after_iterations is None or iterations < stop_after_iterations:
                await asyncio.sleep(interval_seconds)
