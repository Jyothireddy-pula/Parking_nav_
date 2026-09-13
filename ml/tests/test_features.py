import numpy as np

from cv.features import extract_features, to_grayscale


def test_to_grayscale_of_flat_color_image() -> None:
    image = np.full((10, 10, 3), 100, dtype=np.uint8)

    gray = to_grayscale(image)

    assert gray.shape == (10, 10)
    assert np.allclose(gray, 100, atol=0.01)


def test_extract_features_returns_three_values() -> None:
    image = np.random.default_rng(0).integers(0, 255, (20, 20, 3), dtype=np.uint8)

    features = extract_features(image)

    assert features.shape == (3,)


def test_flat_image_has_near_zero_edge_density() -> None:
    flat_image = np.full((20, 20, 3), 128, dtype=np.uint8)

    features = extract_features(flat_image)

    _mean, _std, edge_density = features
    assert edge_density < 1e-9


def test_high_contrast_image_has_higher_edge_density_than_flat() -> None:
    flat_image = np.full((20, 20, 3), 128, dtype=np.uint8)
    checkerboard = np.zeros((20, 20, 3), dtype=np.uint8)
    checkerboard[::2, ::2] = 255
    checkerboard[1::2, 1::2] = 255

    flat_edges = extract_features(flat_image)[2]
    checker_edges = extract_features(checkerboard)[2]

    assert checker_edges > flat_edges
