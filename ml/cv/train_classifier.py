"""Train and evaluate the occupancy classifier on a labeled image folder.

This project has not run this script against real PKLot/CNRPark-EXT data
in this environment (no GPU/large-dataset download in this session) — see
docs/CV.md for the verified current download locations and exactly what
running this script for real would look like. Running it against the
correct folder layout (see cv/dataset.py) works today; the numbers this
prints are only as meaningful as the data you point it at, and this
script will never claim an accuracy it didn't just compute.

Usage:
    python -m cv.train_classifier \\
        --train-dir /path/to/pklot/train --test-dir /path/to/pklot/test \\
        --output model.joblib
"""

import argparse
from pathlib import Path

from cv.classifier import OccupancyClassifier
from cv.dataset import load_labeled_image_folder


def train_and_evaluate(train_dir: Path, test_dir: Path, output_path: Path) -> float:
    train_features, train_labels = load_labeled_image_folder(train_dir)
    test_features, test_labels = load_labeled_image_folder(test_dir)

    classifier = OccupancyClassifier()
    classifier.train(train_features, train_labels)
    accuracy = classifier.evaluate(test_features, test_labels)
    classifier.save(output_path)
    return accuracy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--train-dir", required=True, type=Path)
    parser.add_argument("--test-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    accuracy = train_and_evaluate(args.train_dir, args.test_dir, args.output)
    print(f"[OK] held-out test accuracy: {accuracy:.4f} (measured on {args.test_dir}, label this data's provenance)")
    print(f"[OK] saved model to {args.output}")


if __name__ == "__main__":
    main()
