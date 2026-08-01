"""POIZON 구매자 취소가능 창 수집 보류 테스트 (2026-08-01).

POIZON 은 결제 후 1시간 동안 구매자가 자유롭게 취소할 수 있다. 창 안의 주문을
미리 수집하면 곧바로 취소돼 삼바에 유령 주문이 남으므로, 수집 경로(order_sync·
주문폴러)는 is_buyer_cancelable 로 창이 지난 주문만 받는다. 수집 전에 취소된
주문은 is_canceled 로 영구 제외한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.domain.samba.proxy.poison import (
    POISON_CANCEL_WINDOW_MIN,
    is_buyer_cancelable,
    is_canceled,
)

KST = timezone(timedelta(hours=9))


def _pay_time(minutes_ago: int) -> str:
    return (datetime.now(tz=KST) - timedelta(minutes=minutes_ago)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def test_within_window_is_cancelable():
    order = {"order_status": 2000, "pay_time": _pay_time(10)}
    assert is_buyer_cancelable(order) is True


def test_past_window_is_not_cancelable():
    order = {"order_status": 2000, "pay_time": _pay_time(POISON_CANCEL_WINDOW_MIN + 5)}
    assert is_buyer_cancelable(order) is False


def test_unpaid_is_always_cancelable():
    # 결제대기(1000)는 pay_time 이 없어도 항상 보류
    assert is_buyer_cancelable({"order_status": 1000, "pay_time": ""}) is True


def test_canceled_is_not_window_target():
    # 이미 취소된 주문은 창 판정 대상이 아님 — 수집 여부는 is_canceled 로 별도 판단
    order = {"order_status": 7000, "pay_time": _pay_time(10)}
    assert is_buyer_cancelable(order) is False
    assert is_canceled(order) is True


def test_canceled_codes():
    for code in (7000, 8000, 8010, 8080):
        assert is_canceled({"order_status": code}) is True
    for code in (1000, 2000, 2100, 2800, 4000):
        assert is_canceled({"order_status": code}) is False


def test_missing_or_bad_pay_time_keeps_legacy_ingest():
    # pay_time 없음/파싱불가 + 결제 이후 상태 → 기존과 같이 수집(False)
    assert is_buyer_cancelable({"order_status": 2000, "pay_time": ""}) is False
    assert is_buyer_cancelable({"order_status": 2000, "pay_time": "N/A"}) is False


def test_custom_window_override():
    order = {"order_status": 2000, "pay_time": _pay_time(30)}
    assert is_buyer_cancelable(order, window_min=20) is False
    assert is_buyer_cancelable(order, window_min=60) is True
