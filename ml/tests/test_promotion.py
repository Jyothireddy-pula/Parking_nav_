import pytest

from cv.promotion import CV_AUTO, CV_VERIFIED, decide_collection_method


def test_low_mae_relative_to_capacity_promotes_to_cv_auto() -> None:
    # 5 spaces of error on a 100-space lot = 5% < 10% threshold
    assert decide_collection_method(mae=5.0, total_capacity=100) == CV_AUTO


def test_high_mae_relative_to_capacity_stays_cv_verified() -> None:
    # 15 spaces of error on a 100-space lot = 15% >= 10% threshold
    assert decide_collection_method(mae=15.0, total_capacity=100) == CV_VERIFIED


def test_exactly_at_threshold_is_not_promoted() -> None:
    # Exactly 10% is not "< 10%" — stays cv_verified.
    assert decide_collection_method(mae=10.0, total_capacity=100) == CV_VERIFIED


def test_zero_mae_is_promoted() -> None:
    assert decide_collection_method(mae=0.0, total_capacity=50) == CV_AUTO


def test_negative_mae_is_rejected() -> None:
    with pytest.raises(ValueError, match="mae"):
        decide_collection_method(mae=-1.0, total_capacity=100)


def test_non_positive_capacity_is_rejected() -> None:
    with pytest.raises(ValueError, match="total_capacity"):
        decide_collection_method(mae=1.0, total_capacity=0)
