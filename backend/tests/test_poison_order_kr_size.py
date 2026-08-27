"""POIZON 주문 옵션에 한국 사이즈(mm) 병기 테스트 (2026-08-21).

배경:
- 포이즌 주문에는 EU 표기(properties)만 들어오는데 소싱처는 mm 표기라, 살 때마다
  포이즌 사이즈표를 눈으로 대조해야 했다.
- 포이즌이 SKU 마다 사이즈 대조표(KR/EU/UK/JP/US)를 주므로 품번 단위로 1회 조회해
  'EU 44.5 · KR 285' 처럼 옵션 옆에 붙인다.
- 대조표에 한국 사이즈가 없는 SPU 가 실제로 있다(EU 만 있는 경우). 그런 건은 임의
  환산표로 채우지 않고 원본 그대로 둔다 — 신뢰서열이 박스실측 > 포이즌 > 소싱처라,
  소싱처 공용표로 덮으면 오구매가 난다.

테스트 방식:
- order.py 는 모듈 최상단에서 dtos.user ↔ domain.user 순환참조를 유발해 cold import
  불가(test_coupang_match_sellerproduct_fallback.py 와 동일 제약).
  → 순수 헬퍼만 AST 로 떼어내 실제로 실행한다(문자열 검사보다 강한 계약).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from backend.domain.samba.proxy.poison import kr_size_mm

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ORDER_PY = BACKEND_ROOT / "backend/api/v1/routers/samba/order.py"

_WANTED = {"_poison_size_token", "_poison_kr_size", "_poison_option_label"}


def _load_helpers() -> dict[str, Any]:
    """order.py 에서 순수 헬퍼 함수만 떼어내 실행 가능한 네임스페이스로 만든다."""
    tree = ast.parse(ORDER_PY.read_text(encoding="utf-8"))
    picked = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in _WANTED
    ]
    missing = _WANTED - {node.name for node in picked}
    assert not missing, f"헬퍼 누락: {sorted(missing)}"
    module = ast.fix_missing_locations(ast.Module(body=picked, type_ignores=[]))
    namespace: dict[str, Any] = {"re": re}
    exec(compile(module, str(ORDER_PY), "exec"), namespace)  # noqa: S102
    return namespace


_H = _load_helpers()
_size_token = _H["_poison_size_token"]
_option_label = _H["_poison_option_label"]


# ── 사이즈 대조표 → mm ────────────────────────────────────────────────────
def test_kr_key_wins():
    cand = {
        "KR": "285",
        "US Men": "10.5",
        "US Women": "12",
        "EU": "44.5",
        "UK": "9.5",
        "JP": "28.5",
    }
    assert kr_size_mm(cand) == 285


def test_kr_with_parenthetical_suffix():
    # '280 (EU 44⅔)' 처럼 설명이 붙어 오는 경우가 있다
    assert kr_size_mm({"KR": "280 (EU 44 2/3)"}) == 280


def test_chn_fallback_when_no_kr():
    # 신발 중국 사이즈는 mm 기준이라 KR 과 같은 값
    assert kr_size_mm({"CHN": "250", "EU": "40"}) == 250


def test_jp_fallback_is_cm_times_ten():
    assert kr_size_mm({"JP": "28.5", "EU": "44.5"}) == 285


def test_us_only_is_not_converted():
    """EU/UK/US 만 있는 SKU 는 표기를 비운다 — 환산식으로 지어내지 않는다.

    실측(2026-08-24): MLB 아동화 7ASXLM06N-50WHS 는 포이즌이 EU/US/UK 만 주는데,
    성인 남성 환산식(180+US×10)을 대면 EU 33.5·US 2 → 200mm 가 나온다.
    실제 한국 사이즈는 210mm 로 10mm 짧다. 아동·유스 구간에서 그 식이 안 맞는다.
    """
    assert kr_size_mm({"EU": "33.5", "US": "2", "UK": "1.5"}) is None
    assert kr_size_mm({"EU": "32", "US": "1", "UK": "13.5"}) is None
    assert kr_size_mm({"EU": "43", "US": "10", "UK": "9"}) is None
    assert kr_size_mm({"EU": "43", "US Men": "10", "UK": "9"}) is None
    assert kr_size_mm({"EU": "39", "US Women": "8"}) is None


def test_chart_value_still_wins_when_us_present():
    """US 가 같이 와도 표에 KR/JP 가 있으면 그걸 읽는다."""
    assert kr_size_mm({"KR": "285", "US Men": "10.5", "EU": "44.5"}) == 285
    assert kr_size_mm({"JP": "28.5", "US": "10.5", "EU": "44.5"}) == 285


# ── 옵션 문자열에서 사이즈 토큰 추출 ──────────────────────────────────────
def test_size_token_is_last_field():
    # 운영 주문에서 실제로 관측된 표기들 (색상·구성이 앞, 사이즈가 맨 뒤)
    assert _size_token("EU 46") == "46"
    assert _size_token("EU 흰색 녹색 EU 35.5") == "35.5"
    assert _size_token("EU 블랙 EU 41-42") == "41-42"
    assert _size_token("화이트 37.5") == "37.5"
    assert _size_token("화이트/다크 인디고 2XL") == "2XL"
    assert _size_token("") == ""


# ── 최종 옵션 표기 ────────────────────────────────────────────────────────
def test_label_appends_kr_by_sku_id():
    item = {"properties": "EU 44.5", "sku_id": 12345}
    assert _option_label(item, {"S:12345": 285}) == "EU 44.5 · KR 285"


def test_label_falls_back_to_size_string_when_sku_id_misses():
    # 주문의 sku_id 가 카탈로그 skuId 와 다른 체계일 때의 폴백 경로
    item = {"properties": "EU 흰색 녹색 EU 35.5", "article_number": "DX9176-106"}
    index = {"A:DX9176-106|35.5": 225}
    assert _option_label(item, index) == "EU 흰색 녹색 EU 35.5 · KR 225"


def test_label_unchanged_when_no_match():
    # 의류처럼 mm 이 없는 경우 — 원본 그대로 두고 임의 환산하지 않는다
    assert _option_label({"properties": "화이트 S"}, {"S:1": 280}) == "화이트 S"
    assert _option_label({"properties": "EU 46"}, None) == "EU 46"


def test_label_is_idempotent():
    # 재동기화 때마다 원본 properties 에서 다시 만들므로 KR 이 중복 누적되지 않는다
    item = {"properties": "EU 44.5", "sku_id": 12345}
    index = {"S:12345": 285}
    assert (
        _option_label(item, index) == _option_label(item, index) == ("EU 44.5 · KR 285")
    )


# ── 배선 계약 (정적) ──────────────────────────────────────────────────────
class TestWiring:
    """헬퍼가 실제 주문동기화 경로에 연결돼 있는지 — 배선이 끊기는 회귀 차단."""

    def test_sync_loop_prefetches_kr_sizes(self) -> None:
        src = ORDER_PY.read_text(encoding="utf-8")
        assert "_po_kr = await _fetch_poison_kr_sizes(" in src, (
            "POIZON 동기화 루프에서 한국사이즈 프리페치 누락"
        )
        # ruff 줄바꿈에 따라 한 줄/여러 줄이 왔다갔다하므로 공백은 정규식으로 흡수
        assert re.search(
            r'_parse_poison_order\(\s*ro,\s*account\["id"\],\s*label,\s*kr_sizes=_po_kr\s*\)',
            src,
        ), "_parse_poison_order 에 kr_sizes 전달 누락"

    def test_parser_uses_option_label(self) -> None:
        src = ORDER_PY.read_text(encoding="utf-8")
        assert '"product_option": _poison_option_label(item, kr_sizes),' in src, (
            "product_option 이 원본 properties 로 되돌아감 — KR 병기 사라짐"
        )

    def test_append_only_update_allowed(self) -> None:
        """이미 수집된 주문도 KR 이 소급 반영되도록 append 갱신 경로 유지."""
        src = ORDER_PY.read_text(encoding="utf-8")
        assert 'order_data["product_option"].startswith(' in src, (
            "append-only 옵션 갱신 경로 누락 — 기존 주문에 KR 이 안 붙는다"
        )
