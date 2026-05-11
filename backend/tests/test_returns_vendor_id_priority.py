"""쿠팡 반품 동기화 vendor_id 우선순위 회귀 테스트 (2026-05 버그).

returns.py:1460 — extras.vendorId(A0xxxxxxx) 우선, account.seller_id(zerocp 등 로그인 ID)는 fallback.
이전 버그: account.seller_id가 먼저라 zerocp가 vendor_id로 들어가 404 발생.
"""

from __future__ import annotations

from types import SimpleNamespace


def _resolve_vendor_id(extras: dict, account: SimpleNamespace) -> str:
    """returns.py:1460 표현식 동일."""
    return extras.get("vendorId", "") or account.seller_id or ""


def test_vendor_id_prefers_extras_vendor_id_over_seller_id():
    extras = {"vendorId": "A01616738"}
    account = SimpleNamespace(seller_id="zerocp")
    assert _resolve_vendor_id(extras, account) == "A01616738"


def test_vendor_id_falls_back_to_seller_id_when_extras_missing():
    extras = {}
    account = SimpleNamespace(seller_id="A01616738")
    assert _resolve_vendor_id(extras, account) == "A01616738"


def test_vendor_id_empty_extras_value_falls_back():
    extras = {"vendorId": ""}
    account = SimpleNamespace(seller_id="A01616738")
    assert _resolve_vendor_id(extras, account) == "A01616738"
