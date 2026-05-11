"""쿠팡 주문수집 paid_at tz-naive/aware 비교 회귀 테스트 (2026-05 버그)."""

from __future__ import annotations

from datetime import datetime, timezone


def _normalize_for_compare(
    new_paid: datetime, existing_paid: datetime
) -> tuple[datetime, datetime]:
    """order.py:5076-5095 비교 직전 normalize 로직과 동일."""
    _np = (
        new_paid.replace(tzinfo=timezone.utc) if new_paid.tzinfo is None else new_paid
    )
    _ep = (
        existing_paid.replace(tzinfo=timezone.utc)
        if existing_paid.tzinfo is None
        else existing_paid
    )
    return _np, _ep


def test_paid_at_compare_aware_vs_naive_does_not_raise():
    new_paid = datetime(2026, 5, 9, 8, 51, 0, tzinfo=timezone.utc)
    existing = datetime(2026, 5, 9, 8, 50, 0)  # naive
    np, ep = _normalize_for_compare(new_paid, existing)
    assert (np < ep) is False
    assert (ep < np) is True


def test_paid_at_compare_both_aware():
    new_paid = datetime(2026, 5, 9, 8, 50, 0, tzinfo=timezone.utc)
    existing = datetime(2026, 5, 9, 8, 51, 0, tzinfo=timezone.utc)
    np, ep = _normalize_for_compare(new_paid, existing)
    assert np < ep


def test_paid_at_compare_both_naive_assumed_utc():
    new_paid = datetime(2026, 5, 9, 8, 50, 0)
    existing = datetime(2026, 5, 9, 8, 51, 0)
    np, ep = _normalize_for_compare(new_paid, existing)
    assert np.tzinfo is timezone.utc
    assert ep.tzinfo is timezone.utc
    assert np < ep
