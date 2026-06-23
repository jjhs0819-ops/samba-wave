"""스토어케어 추천 분모 N = '삼바 주문수' + 과소집계 버퍼 회귀 테스트 (2026-06-23).

사용자 결정: 주문이행률(SSG/11번가)의 전체주문수 N 을 포털값 대신 삼바 주문수로 —
매일 삼바에서 검증 가능. 삼바 N 이 마켓보다 작을 수 있어 +5% 버퍼로 과소구매 방지.
GS(품절률)는 매핑 제외 → 포털 N 유지. 삼바 카운트 실패/0 이면 포털 N 폴백.
"""
from __future__ import annotations

import asyncio


def test_buffer_inflates_n():
    from backend.domain.samba.store_care import service as svc

    assert svc._N_BUFFER_PCT == 5
    assert svc._buffered_n(100) == 105
    assert svc._buffered_n(13) == 14  # ceil(13.65)
    assert svc._buffered_n(0) == 0


def test_samba_n_cfg_covers_fulfillment_markets_only():
    from backend.domain.samba.store_care import service as svc

    assert "ssg" in svc._SAMBA_N_CFG
    assert "11st" in svc._SAMBA_N_CFG
    # GS 품절률은 N 매핑 제외 → 포털 N 유지
    assert "gsshop" not in svc._SAMBA_N_CFG


def test_count_returns_none_for_unmapped_market():
    """매핑 없는 마켓(gsshop)은 세션 사용 전에 None — 포털 N 폴백 경로."""
    from backend.domain.samba.store_care import service as svc

    res = asyncio.run(svc._count_samba_order_n(None, "gsshop", None))
    assert res is None


def test_buffer_increases_recommendation_qty():
    """버퍼가 추천 구매갯수를 늘려 과소구매를 방지한다."""
    from backend.domain.samba.store_care.service import (
        _buffered_n,
        recommend_purchase_qty,
    )

    target = {"metric": "order_fulfillment", "value": 90.0}
    q_plain = recommend_purchase_qty(target, 85.0, 100)["qty"]
    q_buf = recommend_purchase_qty(target, 85.0, _buffered_n(100))["qty"]

    assert q_plain == 50  # ceil(100*(0.90-0.85)/(1-0.90))
    assert q_buf == 53  # ceil(105*0.05/0.10) = ceil(52.5)
    assert q_buf > q_plain, f"버퍼가 추천을 늘리지 못함: plain={q_plain} buf={q_buf}"


class _FakeResult:
    def __init__(self, rows=None, scalar_val=None):
        self._rows = rows or []
        self._scalar = scalar_val

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar


class _FakeSession:
    """1st execute → 마켓계정 channel_id 목록, 2nd execute → 주문 COUNT."""

    def __init__(self):
        self._n = 0

    async def execute(self, _stmt):
        self._n += 1
        if self._n == 1:
            return _FakeResult(rows=[("chan-1",), ("chan-2",)])
        return _FakeResult(scalar_val=42)


def test_count_samba_n_returns_order_count():
    from backend.domain.samba.store_care import service as svc

    n = asyncio.run(svc._count_samba_order_n(_FakeSession(), "11st", tenant_id="t1"))
    assert n == 42
