import numpy as np

from cv.blur import is_blurry, laplacian_variance


def test_flat_image_has_zero_laplacian_variance() -> None:
    flat_image = np.full((30, 30, 3), 128, dtype=np.uint8)

    assert laplacian_variance(flat_image) == 0.0


def test_flat_image_is_blurry() -> None:
    flat_image = np.full((30, 30, 3), 128, dtype=np.uint8)

    assert is_blurry(flat_image) is True


def test_sharp_high_contrast_image_is_not_blurry() -> None:
    rng = np.random.default_rng(1)
    sharp_image = rng.integers(0, 255, (30, 30, 3), dtype=np.uint8)

    assert is_blurry(sharp_image, threshold=1.0) is False


def test_threshold_is_configurable() -> None:
    rng = np.random.default_rng(2)
    image = rng.integers(100, 160, (30, 30, 3), dtype=np.uint8)

    variance = laplacian_variance(image)

    assert is_blurry(image, threshold=variance + 1) is True
    assert is_blurry(image, threshold=max(variance - 1, 0)) is False
