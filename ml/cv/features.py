"""Handcrafted features for the occupancy classifier.

Deliberately not a deep CNN: this project has no GPU budget and no
verified-working real training run in this environment, so a small,
fast, inspectable classical-ML baseline is what's actually built and
tested here. Swapping in a CNN later only requires replacing
`extract_features` and retraining — the rest of the pipeline (polygons,
promotion rule, low-confidence handling) doesn't change.
"""

import numpy as np


def to_grayscale(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image.astype(np.float64)
    # Standard luma weights.
    return image[..., :3].astype(np.float64) @ np.array([0.2989, 0.5870, 0.1140])


def _sobel_edge_magnitude(gray: np.ndarray) -> np.ndarray:
    gx_kernel = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=np.float64)
    gy_kernel = gx_kernel.T

    padded = np.pad(gray, 1, mode="edge")
    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    for i in range(3):
        for j in range(3):
            window = padded[i : i + gray.shape[0], j : j + gray.shape[1]]
            gx += window * gx_kernel[i, j]
            gy += window * gy_kernel[i, j]
    return np.sqrt(gx**2 + gy**2)


def extract_features(image: np.ndarray) -> np.ndarray:
    """A parking space crop -> a small fixed-length feature vector:
    mean intensity, intensity std-dev, and mean edge magnitude (texture/
    edge density — an empty space is typically flatter than one with a
    parked vehicle's edges and shadows)."""

    gray = to_grayscale(image)
    edges = _sobel_edge_magnitude(gray)
    return np.array([gray.mean(), gray.std(), edges.mean()], dtype=np.float64)
