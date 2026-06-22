"""송장수집 취소요청 제외 = '스킵' 분류 회귀 테스트 (2026-06-22).

취소요청 주문은 송장 추출 대상이 아니라 enqueue_for_order 단계에서 제외된다.
이전엔 success=False + error 로 반환 → 자동실행 이력에 '오류 N건'으로 빨갛게 집계되어
'송장수집 실패'로 오해됨(팀장 문의). 까대기/선물주문 등 다른 정상 제외와 동일하게
success=True + skipped 로 분류해 '스킵'으로 잡히게 한다(기능 변화 없음, 분류만).
"""

from __future__ import annotations

import asyncio


class _FakeOrder:
    id = "ord_test"
    status = "cancel_requested"
    shipping_status = ""
    sourcing_order_number = "SO123"


class _FakeSession:
    async def get(self, _model, _oid):
        return _FakeOrder()

    async def execute(self, *a, **k):
        return None

    async def commit(self):
        return None


class _FakeCtx:
    async def __aenter__(self):
        return _FakeSession()

    async def __aexit__(self, *exc):
        return False


def test_cancelled_order_classified_as_skip_not_error(monkeypatch):
    """취소요청 주문 enqueue = 스킵(정상 제외)으로 분류, 오류 아님."""
    from backend.domain.samba.tracking_sync import service as svc

    monkeypatch.setattr(svc, "get_write_session", lambda: _FakeCtx())
    monkeypatch.setattr(svc, "is_order_cancelled", lambda _order: True)

    res = asyncio.run(svc.enqueue_for_order("ord_test"))

    assert res.get("skipped") is True, f"취소요청이 스킵으로 분류 안 됨: {res}"
    assert res.get("success") is True, (
        f"취소요청 제외가 오류(success=False)로 잡힘: {res}"
    )
    assert "error" not in res, (
        f"취소요청에 error 필드 잔존(자동실행 이력 '오류'로 집계): {res}"
    )
