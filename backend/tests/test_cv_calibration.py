from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_loader.loader import load_campus_config_file
from app.config_loader.upsert import upsert_campus_config
from app.schemas.ingestion import ObservationIn
from app.services.campus_config import CampusNotFoundError
from app.services.cv_calibration import (
    CV_AUTO,
    CV_VERIFIED,
    CvCalibrationService,
    InsufficientPairedDataError,
    ParkingLotNotFoundError,
    decide_collection_method,
)
from app.services.ingestion import IngestionService

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CAMPUS_PATH = REPO_ROOT / "configs" / "campuses" / "sample.yaml"


@pytest.fixture
def service() -> CvCalibrationService:
    return CvCalibrationService()


@pytest.fixture
async def sample_campus(db_session: AsyncSession) -> str:
    config = load_campus_config_file(SAMPLE_CAMPUS_PATH)
    await upsert_campus_config(db_session, config)
    return config.campus_id


async def _ingest_pair(db_session, campus_id, ts, manual_count, cv_count, cv_method="cv_auto"):
    """Posts a manual ground-truth reading and a CV reading for the same
    lot at the same timestamp — the exact pairing calibration needs.
    This only works because the duplicate check is keyed on
    (campus_id, timestamp, parking_lot_id, collection_method): two
    different collection methods observing the same moment are not
    duplicates of each other."""

    ingestion = IngestionService()
    await ingestion.ingest_one(
        db_session,
        campus_id,
        ObservationIn(
            timestamp=ts,
            parking_lot_id="sample-lot-1",
            occupied_spaces=manual_count,
            source_label="REAL",
            collection_method="manual_count",
        ),
    )
    await ingestion.ingest_cv_batch(
        db_session,
        campus_id,
        [
            ObservationIn(
                timestamp=ts,
                parking_lot_id="sample-lot-1",
                occupied_spaces=cv_count,
                source_label="REAL",
                collection_method=cv_method,
            )
        ],
    )


def test_decide_collection_method_matches_ml_package_threshold() -> None:
    # ml/cv/promotion.py defines the canonical threshold; this constant is
    # duplicated here (see module docstring) and must never drift from it.
    import sys
    from importlib import import_module

    from app.services.cv_calibration import CV_AUTO_PROMOTION_THRESHOLD_FRACTION

    ml_path = str(REPO_ROOT / "ml")
    sys.path.insert(0, ml_path)
    try:
        ml_promotion = import_module("cv.promotion")
    finally:
        sys.path.remove(ml_path)

    assert CV_AUTO_PROMOTION_THRESHOLD_FRACTION == ml_promotion.CV_AUTO_PROMOTION_THRESHOLD_FRACTION


def test_decide_collection_method_boundary() -> None:
    assert decide_collection_method(mae=5.0, total_capacity=100) == CV_AUTO
    assert decide_collection_method(mae=10.0, total_capacity=100) == CV_VERIFIED
    assert decide_collection_method(mae=15.0, total_capacity=100) == CV_VERIFIED


async def test_calibration_report_computes_correct_mae(
    db_session: AsyncSession, service: CvCalibrationService, sample_campus: str
) -> None:
    # sample-lot-1 total_capacity is 100 in configs/campuses/sample.yaml
    pairs = [
        (datetime(2026, 1, 12, 9, 0, tzinfo=timezone.utc), 40, 42),  # |40-42| = 2
        (datetime(2026, 1, 12, 9, 5, tzinfo=timezone.utc), 50, 45),  # |50-45| = 5
        (datetime(2026, 1, 12, 9, 10, tzinfo=timezone.utc), 60, 63),  # |60-63| = 3
    ]
    for ts, manual_count, cv_count in pairs:
        await _ingest_pair(db_session, sample_campus, ts, manual_count, cv_count)

    report = await service.compute_calibration_report(db_session, sample_campus, "sample-lot-1")

    assert report.sample_size == 3
    assert report.mae == pytest.approx((2 + 5 + 3) / 3)
    assert report.campus_id == sample_campus
    assert report.parking_lot_id == "sample-lot-1"
    # MAE ~3.33 on a 100-capacity lot is well under the 10% threshold.
    assert report.recommended_collection_method == CV_AUTO


async def test_calibration_report_recommends_cv_verified_when_error_is_high(
    db_session: AsyncSession, service: CvCalibrationService, sample_campus: str
) -> None:
    ts = datetime(2026, 1, 12, 9, 0, tzinfo=timezone.utc)
    await _ingest_pair(db_session, sample_campus, ts, manual_count=40, cv_count=70)  # |40-70| = 30, 30% of 100

    report = await service.compute_calibration_report(db_session, sample_campus, "sample-lot-1")

    assert report.recommended_collection_method == CV_VERIFIED


async def test_calibration_report_with_no_paired_data_raises(
    db_session: AsyncSession, service: CvCalibrationService, sample_campus: str
) -> None:
    with pytest.raises(InsufficientPairedDataError):
        await service.compute_calibration_report(db_session, sample_campus, "sample-lot-1")


async def test_calibration_report_unknown_campus_raises(
    db_session: AsyncSession, service: CvCalibrationService
) -> None:
    with pytest.raises(CampusNotFoundError):
        await service.compute_calibration_report(db_session, "does-not-exist", "sample-lot-1")


async def test_calibration_report_unknown_lot_raises(
    db_session: AsyncSession, service: CvCalibrationService, sample_campus: str
) -> None:
    with pytest.raises(ParkingLotNotFoundError):
        await service.compute_calibration_report(db_session, sample_campus, "does-not-exist")


async def test_only_timestamps_present_in_both_manual_and_cv_are_paired(
    db_session: AsyncSession, service: CvCalibrationService, sample_campus: str
) -> None:
    ingestion = IngestionService()
    matched_ts = datetime(2026, 1, 12, 9, 0, tzinfo=timezone.utc)
    manual_only_ts = datetime(2026, 1, 12, 9, 5, tzinfo=timezone.utc)

    await _ingest_pair(db_session, sample_campus, matched_ts, manual_count=20, cv_count=22)
    await ingestion.ingest_one(
        db_session,
        sample_campus,
        ObservationIn(
            timestamp=manual_only_ts,
            parking_lot_id="sample-lot-1",
            occupied_spaces=30,
            source_label="REAL",
            collection_method="manual_count",
        ),
    )

    report = await service.compute_calibration_report(db_session, sample_campus, "sample-lot-1")

    assert report.sample_size == 1
    assert report.mae == pytest.approx(2.0)
