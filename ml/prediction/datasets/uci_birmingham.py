"""UCI "Parking Birmingham" dataset -- EXTERNAL, permanently. Verified
current download location (checked live in this session; archive.ics.uci.edu
returned HTTP 200 for this exact URL):

    https://archive.ics.uci.edu/static/public/482/parking+birmingham.zip

Dataset ID 482 on the UCI Machine Learning Repository. 35,717 rows, 30 car
parks operated by NCP for Birmingham City Council, 2016-10-04 to
2016-12-19, columns: SystemCodeNumber, Capacity, Occupancy, LastUpdated.
UK Open Government Licence. Re-verify this URL before a real training run
-- UCI dataset URLs can move.

Like PKLot/CNRPark-EXT in Module 5: any model trained on this is trained
on data labeled EXTERNAL, permanently -- it can prove a model architecture
and pipeline work, never that it is accurate for VIT-AP.
"""

import io
import zipfile
from pathlib import Path

import httpx
import pandas as pd

DOWNLOAD_URL = "https://archive.ics.uci.edu/static/public/482/parking+birmingham.zip"
DATASET_LABEL = "uci_parking_birmingham"


def download(dest_dir: Path) -> Path:
    """Downloads and caches dataset.csv under dest_dir. Network access
    required -- not called from tests, which use a small local fixture
    instead so CI doesn't depend on an external service being reachable."""

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / "dataset.csv"
    if dest_path.exists():
        return dest_path

    response = httpx.get(DOWNLOAD_URL, follow_redirects=True, timeout=60.0)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive, archive.open("dataset.csv") as member:
        dest_path.write_bytes(member.read())
    return dest_path


def load(csv_path: Path) -> pd.DataFrame:
    """Parses the raw UCI CSV into this pipeline's standardized schema:
    [lot_id, timestamp, occupied, capacity]. No gate_inflow/event columns
    -- this dataset doesn't have them, so those features are simply absent
    for this dataset rather than zero-filled."""

    raw = pd.read_csv(csv_path)
    return pd.DataFrame(
        {
            "lot_id": raw["SystemCodeNumber"].astype(str),
            "timestamp": pd.to_datetime(raw["LastUpdated"], utc=True),
            "occupied": raw["Occupancy"].astype(float),
            "capacity": raw["Capacity"].astype(float),
        }
    )
