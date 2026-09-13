"""Occupancy classifier: a logistic regression over the handcrafted
features in features.py. Trained on EXTERNAL data (PKLot/CNRPark-EXT);
see docs/CV.md for why external accuracy can never be presented as VIT-AP
accuracy — that only comes from the calibration report."""

from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression

from cv.features import extract_features

OCCUPIED = "occupied"
VACANT = "vacant"

# Below this predicted-class probability, the prediction is not trusted
# enough to count — see docs/CV.md's low-confidence handling rule.
DEFAULT_CONFIDENCE_THRESHOLD = 0.65


class OccupancyClassifier:
    def __init__(self, model: LogisticRegression | None = None) -> None:
        self._model = model or LogisticRegression(max_iter=1000)
        self._fitted = model is not None

    def train(self, features: np.ndarray, labels: np.ndarray) -> None:
        self._model.fit(features, labels)
        self._fitted = True

    def predict_one(self, image: np.ndarray) -> tuple[str, float]:
        """Returns (label, confidence) for a single space crop.
        confidence is the model's probability for the predicted class."""

        if not self._fitted:
            raise RuntimeError("classifier has not been trained or loaded yet")

        features = extract_features(image).reshape(1, -1)
        proba = self._model.predict_proba(features)[0]
        class_index = int(np.argmax(proba))
        label = self._model.classes_[class_index]
        confidence = float(proba[class_index])
        return label, confidence

    def evaluate(self, features: np.ndarray, labels: np.ndarray) -> float:
        """Accuracy on a held-out set. Callers are responsible for making
        sure this set was not used for training."""

        if not self._fitted:
            raise RuntimeError("classifier has not been trained or loaded yet")
        predictions = self._model.predict(features)
        return float(np.mean(predictions == labels))

    def save(self, path: str | Path) -> None:
        if not self._fitted:
            raise RuntimeError("refusing to save an untrained classifier")
        joblib.dump(self._model, path)

    @classmethod
    def load(cls, path: str | Path) -> "OccupancyClassifier":
        model = joblib.load(path)
        return cls(model=model)
