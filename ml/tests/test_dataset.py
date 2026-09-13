import numpy as np
import pytest
from PIL import Image

from cv.dataset import load_labeled_image_folder
from tests.conftest import make_synthetic_image


def _write_folder(tmp_path, rng: np.random.Generator, count_per_class: int = 5):
    (tmp_path / "occupied").mkdir()
    (tmp_path / "vacant").mkdir()
    for i in range(count_per_class):
        Image.fromarray(make_synthetic_image(True, rng)).save(tmp_path / "occupied" / f"{i}.jpg")
        Image.fromarray(make_synthetic_image(False, rng)).save(tmp_path / "vacant" / f"{i}.jpg")
    return tmp_path


def test_load_labeled_image_folder_reads_both_classes(tmp_path, rng: np.random.Generator) -> None:
    _write_folder(tmp_path, rng)

    features, labels = load_labeled_image_folder(tmp_path)

    assert len(features) == 10
    assert set(labels) == {"occupied", "vacant"}
    assert (labels == "occupied").sum() == 5
    assert (labels == "vacant").sum() == 5


def test_missing_subfolders_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="occupied"):
        load_labeled_image_folder(tmp_path)


def test_empty_folders_raise(tmp_path) -> None:
    (tmp_path / "occupied").mkdir()
    (tmp_path / "vacant").mkdir()

    with pytest.raises(ValueError, match="no labeled images"):
        load_labeled_image_folder(tmp_path)
