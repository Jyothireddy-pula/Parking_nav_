"""Per-lot parking-space polygon annotation.

The interactive part (clicking corners on a reference photo) needs a
human and a display, so it isn't unit-tested — see `main()` below. The
data model, save/load, and crop extraction are pure functions and are
tested.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class SpacePolygon:
    space_id: str
    # Ordered [x, y] pixel corners in the reference photo, closed implicitly
    # (last point connects back to the first). At least 3 points.
    points: list[list[float]]

    def __post_init__(self) -> None:
        if len(self.points) < 3:
            raise ValueError(f"space {self.space_id!r} polygon needs at least 3 points, got {len(self.points)}")


@dataclass(frozen=True)
class LotAnnotation:
    campus_id: str
    parking_lot_id: str
    reference_photo: str
    spaces: list[SpacePolygon]


def save_polygons(annotation: LotAnnotation, path: str | Path) -> None:
    payload = {
        "campus_id": annotation.campus_id,
        "parking_lot_id": annotation.parking_lot_id,
        "reference_photo": annotation.reference_photo,
        "spaces": [asdict(space) for space in annotation.spaces],
    }
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_polygons(path: str | Path) -> LotAnnotation:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    spaces = [SpacePolygon(space_id=s["space_id"], points=s["points"]) for s in payload["spaces"]]
    return LotAnnotation(
        campus_id=payload["campus_id"],
        parking_lot_id=payload["parking_lot_id"],
        reference_photo=payload["reference_photo"],
        spaces=spaces,
    )


def crop_space(image: np.ndarray, polygon: SpacePolygon) -> np.ndarray:
    """Axis-aligned bounding-box crop of a space's polygon. A full
    polygon mask would exclude background more precisely, but a bounding
    box is enough signal for the classifier's handcrafted features and
    keeps this simple to reason about and test."""

    xs = [p[0] for p in polygon.points]
    ys = [p[1] for p in polygon.points]
    x_min, x_max = max(0, int(min(xs))), min(image.shape[1], int(max(xs)) + 1)
    y_min, y_max = max(0, int(min(ys))), min(image.shape[0], int(max(ys)) + 1)
    if x_max <= x_min or y_max <= y_min:
        raise ValueError(f"space {polygon.space_id!r} polygon has no area within the image bounds")
    return image[y_min:y_max, x_min:x_max]


def main() -> None:  # pragma: no cover - interactive tool, not unit-tested
    import argparse

    import matplotlib.pyplot as plt
    from PIL import Image

    parser = argparse.ArgumentParser(
        description="Click each parking space's corners (3+ points), close the window to move to the next space."
    )
    parser.add_argument("--campus-id", required=True)
    parser.add_argument("--parking-lot-id", required=True)
    parser.add_argument("--reference-photo", required=True, type=Path)
    parser.add_argument("--space-ids", nargs="+", required=True, help="One ID per space, in the order you'll click")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    with Image.open(args.reference_photo) as img:
        image = np.array(img.convert("RGB"))

    spaces = []
    for space_id in args.space_ids:
        fig, ax = plt.subplots()
        ax.imshow(image)
        ax.set_title(f"Click corners for space {space_id!r}, then close this window")
        points = fig.ginput(n=-1, timeout=0)
        plt.close(fig)
        spaces.append(SpacePolygon(space_id=space_id, points=[[float(x), float(y)] for x, y in points]))

    annotation = LotAnnotation(
        campus_id=args.campus_id,
        parking_lot_id=args.parking_lot_id,
        reference_photo=str(args.reference_photo),
        spaces=spaces,
    )
    save_polygons(annotation, args.output)
    print(f"[OK] wrote {len(spaces)} space polygon(s) to {args.output}")


if __name__ == "__main__":  # pragma: no cover
    main()
