"""Loads a labeled image folder for training/evaluation.

Expected layout (matches how PKLot/CNRPark-EXT are commonly repackaged
for binary classification):

    <root>/occupied/*.jpg
    <root>/vacant/*.jpg

Any dataset loaded through this function must be labeled at the call
site — this module has no opinion on whether the data is EXTERNAL,
SAMPLE, or something else. See docs/CV.md: PKLot/CNRPark-EXT are always
EXTERNAL, permanently, even after a model is trained on them.
"""

from pathlib import Path

import numpy as np
from PIL import Image

from cv.classifier import OCCUPIED, VACANT
from cv.features import extract_features

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


def _load_image(path: Path) -> np.ndarray:
    with Image.open(path) as img:
        return np.array(img.convert("RGB"))


def load_labeled_image_folder(root: str | Path) -> tuple[np.ndarray, np.ndarray]:
    root = Path(root)
    occupied_dir = root / "occupied"
    vacant_dir = root / "vacant"
    if not occupied_dir.is_dir() or not vacant_dir.is_dir():
        raise FileNotFoundError(
            f"expected {root}/occupied/ and {root}/vacant/ subfolders, found: "
            f"occupied={occupied_dir.is_dir()}, vacant={vacant_dir.is_dir()}"
        )

    features: list[np.ndarray] = []
    labels: list[str] = []
    for label, directory in ((OCCUPIED, occupied_dir), (VACANT, vacant_dir)):
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            image = _load_image(path)
            features.append(extract_features(image))
            labels.append(label)

    if not features:
        raise ValueError(f"no labeled images found under {root}")

    return np.array(features), np.array(labels)
