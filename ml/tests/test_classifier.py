import numpy as np
import pytest

from cv.classifier import OccupancyClassifier
from cv.features import extract_features
from tests.conftest import make_synthetic_image


def _split(features: np.ndarray, labels: np.ndarray, train_fraction: float = 0.75):
    n = len(features)
    cutoff = int(n * train_fraction)
    idx = np.arange(n)
    rng = np.random.default_rng(7)
    rng.shuffle(idx)
    train_idx, test_idx = idx[:cutoff], idx[cutoff:]
    return features[train_idx], labels[train_idx], features[test_idx], labels[test_idx]


def test_classifier_achieves_reasonable_accuracy_on_held_out_synthetic_set(
    synthetic_dataset: tuple[np.ndarray, np.ndarray],
) -> None:
    features, labels = synthetic_dataset
    train_x, train_y, test_x, test_y = _split(features, labels)

    classifier = OccupancyClassifier()
    classifier.train(train_x, train_y)
    accuracy = classifier.evaluate(test_x, test_y)

    # This is measured on a SYNTHETIC held-out set designed to be easily
    # separable — it proves the train/evaluate code path works, not that
    # the model is accurate on real PKLot/CNRPark-EXT or VIT-AP footage.
    assert accuracy >= 0.9


def test_predict_one_returns_label_and_confidence(rng: np.random.Generator) -> None:
    classifier = OccupancyClassifier()
    features = np.array([extract_features(make_synthetic_image(o, rng)) for o in [True, False] * 10])
    labels = np.array((["occupied", "vacant"]) * 10)
    classifier.train(features, labels)

    label, confidence = classifier.predict_one(make_synthetic_image(True, rng))

    assert label in ("occupied", "vacant")
    assert 0.0 <= confidence <= 1.0


def test_predict_before_training_raises() -> None:
    classifier = OccupancyClassifier()

    with pytest.raises(RuntimeError, match="not been trained"):
        classifier.predict_one(np.zeros((10, 10, 3), dtype=np.uint8))


def test_save_and_load_round_trip(tmp_path, synthetic_dataset: tuple[np.ndarray, np.ndarray]) -> None:
    features, labels = synthetic_dataset
    classifier = OccupancyClassifier()
    classifier.train(features, labels)
    model_path = tmp_path / "model.joblib"
    classifier.save(model_path)

    reloaded = OccupancyClassifier.load(model_path)
    accuracy = reloaded.evaluate(features, labels)

    assert accuracy > 0.5


def test_save_untrained_classifier_raises(tmp_path) -> None:
    classifier = OccupancyClassifier()

    with pytest.raises(RuntimeError, match="untrained"):
        classifier.save(tmp_path / "model.joblib")
