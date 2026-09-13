from datetime import datetime, timezone

import numpy as np
import pytest

from cv.annotate_spaces import LotAnnotation, SpacePolygon
from cv.classifier import OccupancyClassifier
from cv.pipeline import (
    CVPipeline,
    build_cv_batch_payload,
    classify_frame,
)
from tests.conftest import IMAGE_SIZE, make_synthetic_image


@pytest.fixture
def trained_classifier(synthetic_dataset: tuple[np.ndarray, np.ndarray]) -> OccupancyClassifier:
    features, labels = synthetic_dataset
    classifier = OccupancyClassifier()
    classifier.train(features, labels)
    return classifier


def _four_space_annotation() -> LotAnnotation:
    size = IMAGE_SIZE
    return LotAnnotation(
        campus_id="sample",
        parking_lot_id="sample-lot-1",
        reference_photo="lot1.jpg",
        spaces=[
            SpacePolygon("s1", [[0, 0], [size, 0], [size, size], [0, size]]),
            SpacePolygon("s2", [[size, 0], [2 * size, 0], [2 * size, size], [size, size]]),
            SpacePolygon("s3", [[0, size], [size, size], [size, 2 * size], [0, 2 * size]]),
            SpacePolygon("s4", [[size, size], [2 * size, size], [2 * size, 2 * size], [size, 2 * size]]),
        ],
    )


def _compose_frame(occupied_flags: list[bool], rng: np.random.Generator) -> np.ndarray:
    size = IMAGE_SIZE
    frame = np.zeros((2 * size, 2 * size, 3), dtype=np.uint8)
    positions = [(0, 0), (0, size), (size, 0), (size, size)]
    for (row, col), occupied in zip(positions, occupied_flags, strict=True):
        frame[row : row + size, col : col + size] = make_synthetic_image(occupied, rng)
    return frame


def test_classify_frame_aggregates_per_space_results_correctly(
    trained_classifier: OccupancyClassifier, rng: np.random.Generator
) -> None:
    annotation = _four_space_annotation()
    frame = _compose_frame([True, False, True, False], rng)

    result = classify_frame(frame, annotation, trained_classifier, blur_threshold=0.0)

    assert result.total_spaces == 4
    assert result.occupied_count == 2
    assert result.vacant_count == 2
    assert result.low_confidence is False


def test_blurry_frame_is_flagged_low_confidence_and_not_silently_counted(
    trained_classifier: OccupancyClassifier,
) -> None:
    annotation = _four_space_annotation()
    flat_frame = np.full((2 * IMAGE_SIZE, 2 * IMAGE_SIZE, 3), 128, dtype=np.uint8)

    result = classify_frame(flat_frame, annotation, trained_classifier)

    assert result.low_confidence is True
    assert result.occupied_count == 0
    assert result.vacant_count == 0
    assert "blurry" in result.reason


def test_high_uncertainty_frame_is_flagged_low_confidence(
    trained_classifier: OccupancyClassifier, rng: np.random.Generator
) -> None:
    annotation = _four_space_annotation()
    frame = _compose_frame([True, False, True, False], rng)

    result = classify_frame(
        frame, annotation, trained_classifier, blur_threshold=0.0, confidence_threshold=0.999999
    )

    assert result.low_confidence is True
    assert result.uncertain_count > 0


def test_build_cv_batch_payload_is_none_for_low_confidence_frame(trained_classifier: OccupancyClassifier) -> None:
    annotation = _four_space_annotation()
    flat_frame = np.full((2 * IMAGE_SIZE, 2 * IMAGE_SIZE, 3), 128, dtype=np.uint8)
    result = classify_frame(flat_frame, annotation, trained_classifier)

    payload = build_cv_batch_payload("sample-lot-1", datetime.now(timezone.utc), result, "cv_verified")

    assert payload is None


def test_build_cv_batch_payload_shape_for_confident_frame(
    trained_classifier: OccupancyClassifier, rng: np.random.Generator
) -> None:
    annotation = _four_space_annotation()
    frame = _compose_frame([True, False, True, False], rng)
    result = classify_frame(frame, annotation, trained_classifier, blur_threshold=0.0)

    payload = build_cv_batch_payload("sample-lot-1", datetime(2026, 1, 1, tzinfo=timezone.utc), result, "cv_auto")

    assert payload["parking_lot_id"] == "sample-lot-1"
    assert payload["occupied_spaces"] == 2
    assert payload["source_label"] == "REAL"
    assert payload["collection_method"] == "cv_auto"


async def test_pipeline_run_once_posts_correctly_labeled_batch(
    trained_classifier: OccupancyClassifier, rng: np.random.Generator
) -> None:
    annotation = _four_space_annotation()
    frame = _compose_frame([True, False, True, False], rng)

    posted = {}

    class _StubResponse:
        def raise_for_status(self) -> None:
            pass

    async def stub_poster(url: str, payloads: list[dict]) -> _StubResponse:
        posted["url"] = url
        posted["payloads"] = payloads
        return _StubResponse()

    pipeline = CVPipeline(
        campus_id="sample",
        backend_base_url="http://backend.test",
        classifier=trained_classifier,
        lot_annotations={"sample-lot-1": annotation},
        collection_methods={"sample-lot-1": "cv_auto"},
        poster=stub_poster,
        blur_threshold=0.0,
    )

    await pipeline.run_once("sample-lot-1", frame, timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert posted["url"] == "http://backend.test/api/v1/campuses/sample/observations/cv-batch"
    assert len(posted["payloads"]) == 1
    assert posted["payloads"][0]["occupied_spaces"] == 2
    assert posted["payloads"][0]["collection_method"] == "cv_auto"


async def test_pipeline_run_once_skips_posting_for_low_confidence_frame(
    trained_classifier: OccupancyClassifier,
) -> None:
    annotation = _four_space_annotation()
    flat_frame = np.full((2 * IMAGE_SIZE, 2 * IMAGE_SIZE, 3), 128, dtype=np.uint8)

    called = False

    async def stub_poster(url: str, payloads: list[dict]):
        nonlocal called
        called = True

    pipeline = CVPipeline(
        campus_id="sample",
        backend_base_url="http://backend.test",
        classifier=trained_classifier,
        lot_annotations={"sample-lot-1": annotation},
        collection_methods={"sample-lot-1": "cv_auto"},
        poster=stub_poster,
    )

    result = await pipeline.run_once("sample-lot-1", flat_frame)

    assert called is False
    assert result.low_confidence is True


async def test_pipeline_run_once_unknown_lot_raises(trained_classifier: OccupancyClassifier) -> None:
    pipeline = CVPipeline(
        campus_id="sample",
        backend_base_url="http://backend.test",
        classifier=trained_classifier,
        lot_annotations={},
        collection_methods={},
    )

    with pytest.raises(KeyError):
        await pipeline.run_once("does-not-exist", np.zeros((10, 10, 3), dtype=np.uint8))
