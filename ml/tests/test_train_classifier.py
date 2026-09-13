"""Exercises the full train -> evaluate -> save pipeline end to end.

Uses the SYNTHETIC image generator from conftest, standing in for a real
external dataset (PKLot/CNRPark-EXT) so this runs without network access
or a multi-GB download in CI. The accuracy asserted here describes this
synthetic set only — see docs/CV.md for why that number is never
presented as real-world or VIT-AP accuracy.
"""

import numpy as np
from PIL import Image

from cv.train_classifier import train_and_evaluate
from tests.conftest import make_synthetic_image


def _write_split(root, rng: np.random.Generator, count_per_class: int) -> None:
    (root / "occupied").mkdir(parents=True)
    (root / "vacant").mkdir(parents=True)
    for i in range(count_per_class):
        Image.fromarray(make_synthetic_image(True, rng)).save(root / "occupied" / f"{i}.jpg")
        Image.fromarray(make_synthetic_image(False, rng)).save(root / "vacant" / f"{i}.jpg")


def test_train_and_evaluate_on_a_held_out_split(tmp_path, rng: np.random.Generator) -> None:
    train_dir = tmp_path / "train"
    test_dir = tmp_path / "test"
    _write_split(train_dir, rng, count_per_class=30)
    _write_split(test_dir, rng, count_per_class=10)
    model_path = tmp_path / "model.joblib"

    accuracy = train_and_evaluate(train_dir, test_dir, model_path)

    assert 0.0 <= accuracy <= 1.0
    assert accuracy >= 0.85  # measured on the SYNTHETIC held-out split above
    assert model_path.exists()
