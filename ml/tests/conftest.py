"""Synthetic (SYNTHETIC-labeled) image generation for tests.

None of this is real parking-lot imagery and none of the numbers computed
from it are presented as PKLot/CNRPark-EXT or VIT-AP accuracy — it exists
only to exercise the feature extraction / classifier / pipeline code
without needing a real dataset in CI. See docs/CV.md.
"""

import numpy as np
import pytest

IMAGE_SIZE = 48


def make_synthetic_image(occupied: bool, rng: np.random.Generator) -> np.ndarray:
    """A vacant space: fairly flat, low-texture. An occupied space: a
    higher-contrast rectangular blob (stand-in for a parked vehicle) with
    real edges, plus more overall noise. The two classes are made
    deliberately easy to separate — this only proves the pipeline code
    works end-to-end, not that the model is accurate on real photos."""

    base = np.full((IMAGE_SIZE, IMAGE_SIZE, 3), 140, dtype=np.float64)
    base += rng.normal(0, 3, base.shape)

    if occupied:
        top = IMAGE_SIZE // 4
        bottom = IMAGE_SIZE - IMAGE_SIZE // 4
        left = IMAGE_SIZE // 5
        right = IMAGE_SIZE - IMAGE_SIZE // 5
        base[top:bottom, left:right] = 40
        base += rng.normal(0, 12, base.shape)

    return np.clip(base, 0, 255).astype(np.uint8)


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(seed=42)


@pytest.fixture
def synthetic_dataset(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    from cv.features import extract_features

    features = []
    labels = []
    for _ in range(40):
        features.append(extract_features(make_synthetic_image(True, rng)))
        labels.append("occupied")
        features.append(extract_features(make_synthetic_image(False, rng)))
        labels.append("vacant")
    return np.array(features), np.array(labels)
