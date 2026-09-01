"""SSG 브랜드 해석 — 라이브 계약목록(listBrand) 우선 회귀 테스트 (2026-09-01).

배경: 하드코딩 CONTRACTED_BRANDS 에 있던 노스페이스(2000006637)가 실제 계약
해지되어 SSG 가 "더이상 사용하지 않는 브랜드 ID" 로 등록을 거부했다.
→ 라이브 계약목록이 하드코딩보다 우선해야 하고, 라이브에 없는 하드코딩
브랜드는 기타(9999999999) 폴백으로 강제해야 한다.

검증 대상: backend.domain.samba.plugins.markets.ssg._resolve_brand_mappings
(DB/네트워크 접근 없이 get_contracted_brand_map 을 스텁해 순수 단위 검증)
"""

from __future__ import annotations

import asyncio

import pytest

from backend.domain.samba.plugins.markets.ssg import _resolve_brand_mappings
from backend.domain.samba.proxy.ssg import SSGClient


class _FakeClient:
    """get_contracted_brand_map 만 스텁한 가짜 SSGClient."""

    def __init__(self, brand_map: dict[str, str]):
        self._brand_map = brand_map

    async def get_contracted_brand_map(self) -> dict[str, str]:
        return self._brand_map


def _resolve(client, product, mappings=None):
    return asyncio.run(_resolve_brand_mappings(client, product, mappings or []))


# ── 1) 라이브맵에 있는 브랜드 → 라이브 ID 주입 ─────────────────────────────


def test_live_map_hit_injects_live_id():
    # 스케쳐스: 하드코딩(구 2000006059→정정 3000065705)과 무관하게 라이브 ID 사용
    client = _FakeClient({"스케쳐스": "3000065705", "나이키": "2000004827"})
    out = _resolve(client, {"brand": "스케쳐스"})
    assert out == [{"brandNm": "스케쳐스", "brandId": "3000065705"}]


def test_live_map_hit_via_manufacturer():
    client = _FakeClient({"나이키": "2000004827"})
    out = _resolve(client, {"brand": "", "manufacturer": "나이키"})
    assert out == [{"brandNm": "나이키", "brandId": "2000004827"}]


# ── 2) 라이브맵에 없고 하드코딩만 있는 브랜드 → 기타(9999999999) 폴백 ─────


def test_dead_hardcoded_brand_forced_to_etc_fallback():
    # 노스페이스: CONTRACTED_BRANDS 에는 있지만 라이브 계약목록에 없음(계약 해지)
    assert SSGClient.match_brand("노스페이스")[0] == "2000006637"  # 하드코딩 존재 확인
    client = _FakeClient({"나이키": "2000004827"})  # 라이브맵 비어있지 않음
    out = _resolve(client, {"brand": "노스페이스"})
    assert out == [{"brandNm": "노스페이스", "brandId": "9999999999"}]


def test_unknown_brand_no_injection_keeps_etc_fallback():
    # 라이브맵에도 하드코딩에도 없는 브랜드 → 주입 없이 기존 기타 폴백 경로
    client = _FakeClient({"나이키": "2000004827"})
    out = _resolve(client, {"brand": "써코니"})
    assert out == []


# ── 3) 라이브맵 조회 실패({}) → 기존 하드코딩 동작 유지 ───────────────────


def test_live_map_empty_keeps_hardcoded_behavior():
    client = _FakeClient({})  # API 실패 시 get_contracted_brand_map 은 {} 반환
    out = _resolve(client, {"brand": "노스페이스"})
    assert out == []  # 주입 없음 → transform_product 가 하드코딩 폴백 사용 (기존 동작)
    assert SSGClient.match_brand("노스페이스")[0] == "2000006637"


def test_live_map_fetch_exception_keeps_hardcoded_behavior():
    class _Boom:
        async def get_contracted_brand_map(self):
            raise RuntimeError("listBrand down")

    out = _resolve(_Boom(), {"brand": "노스페이스"})
    assert out == []


# ── 정책 매핑(ssgBrandMappings) 최우선 유지 ────────────────────────────────


def test_policy_mapping_untouched(monkeypatch):
    called = False

    class _Spy:
        async def get_contracted_brand_map(self):
            nonlocal called
            called = True
            return {"노스페이스": "1234567890"}

    existing = [{"brandNm": "노스페이스", "brandId": "9000000001"}]
    out = _resolve(_Spy(), {"brand": "노스페이스"}, existing)
    assert out == existing  # 정책 매핑 그대로 — 라이브 조회조차 안 함
    assert called is False


# ── 하드코딩 정정 확인 — 스케쳐스 ID ──────────────────────────────────────


def test_skechers_hardcoded_id_corrected():
    assert SSGClient.match_brand("스케쳐스") == ("3000065705", "스케쳐스")
    assert SSGClient.match_brand("skechers") == ("3000065705", "스케쳐스")


# ── 기타 폴백 주입이 상품명 브랜드 제거를 바꾸지 않는지 (transform 등가성) ──


def test_etc_fallback_injection_transform_equivalent():
    """9999999999 주입이 기존 기타 폴백과 transform 결과가 완전 동일해야 한다.

    기존 기타 폴백: match_brand → ("9999999999","") → step1 no-op,
    step1-2 에서 소싱처 brand 필드를 직접 제거.
    주입 후: _match_from_mappings 가 (9999999999, 원본브랜드명) 매칭 →
    step1 에서 동일 문자열 제거, step1-2 스킵. 전체 결과 dict 동일 확인.
    """
    client = SSGClient("test-key")
    prod = {
        "name": "무스탕패딩 뉴트리아 방한 자켓",
        "brand": "무스탕패딩",  # 하드코딩/라이브 어디에도 없는 가상 브랜드
        "sale_price": 10000,
        "options": [],
    }
    baseline = client.transform_product(
        dict(prod), category_id="123", brand_mappings=[]
    )
    injected = client.transform_product(
        dict(prod),
        category_id="123",
        brand_mappings=[{"brandNm": "무스탕패딩", "brandId": "9999999999"}],
    )
    assert injected == baseline
    assert injected.get("brandId") == "9999999999"
    assert injected.get("itemNm") == "뉴트리아 방한 자켓"


@pytest.mark.parametrize("brand", ["노스페이스", "게스", "스노우피크"])
def test_dead_brands_all_forced_to_etc(brand):
    client = _FakeClient({"나이키": "2000004827"})
    out = _resolve(client, {"brand": brand})
    assert out == [{"brandNm": brand, "brandId": "9999999999"}]
