import numpy as np
import pytest

from cv.annotate_spaces import LotAnnotation, SpacePolygon, crop_space, load_polygons, save_polygons


def test_polygon_requires_at_least_three_points() -> None:
    with pytest.raises(ValueError, match="at least 3 points"):
        SpacePolygon(space_id="s1", points=[[0, 0], [1, 1]])


def test_save_and_load_round_trip(tmp_path) -> None:
    annotation = LotAnnotation(
        campus_id="sample",
        parking_lot_id="sample-lot-1",
        reference_photo="lot1.jpg",
        spaces=[
            SpacePolygon(space_id="s1", points=[[0, 0], [10, 0], [10, 10], [0, 10]]),
            SpacePolygon(space_id="s2", points=[[10, 0], [20, 0], [20, 10]]),
        ],
    )
    path = tmp_path / "lot1_spaces.json"

    save_polygons(annotation, path)
    loaded = load_polygons(path)

    assert loaded == annotation


def test_crop_space_returns_the_bounding_box() -> None:
    image = np.arange(400).reshape(20, 20).astype(np.uint8) % 255
    image = np.stack([image] * 3, axis=-1)
    polygon = SpacePolygon(space_id="s1", points=[[2, 3], [8, 3], [8, 9], [2, 9]])

    crop = crop_space(image, polygon)

    assert crop.shape == (7, 7, 3)


def test_crop_space_outside_image_bounds_raises() -> None:
    image = np.zeros((10, 10, 3), dtype=np.uint8)
    polygon = SpacePolygon(space_id="s1", points=[[-5, -5], [-1, -5], [-1, -1]])

    with pytest.raises(ValueError, match="no area"):
        crop_space(image, polygon)
