"""Blur/occlusion detection. A classifier prediction on a blurry or
occluded frame is not trustworthy no matter how confident the model
claims to be, so this check runs before classification and can veto the
whole frame."""

import numpy as np

from cv.features import to_grayscale

# Variance of the Laplacian below this is treated as "too blurry to trust."
# This threshold is a starting point, not a measured constant — recalibrate
# once real VIT-AP camera footage is available (see docs/CV.md).
DEFAULT_BLUR_VARIANCE_THRESHOLD = 100.0

_LAPLACIAN_KERNEL = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float64)


def laplacian_variance(image: np.ndarray) -> float:
    gray = to_grayscale(image)
    padded = np.pad(gray, 1, mode="edge")
    response = np.zeros_like(gray)
    for i in range(3):
        for j in range(3):
            window = padded[i : i + gray.shape[0], j : j + gray.shape[1]]
            response += window * _LAPLACIAN_KERNEL[i, j]
    return float(response.var())


def is_blurry(image: np.ndarray, threshold: float = DEFAULT_BLUR_VARIANCE_THRESHOLD) -> bool:
    return laplacian_variance(image) < threshold
