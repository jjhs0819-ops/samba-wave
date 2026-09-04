"""더현대 '일시품절' 판정 회귀 테스트 — itemSellGbcd=="11" 은 판매 불가.

2026-09-04 실측으로 확인한 사이트 규격:
- 일시품절 상품도 uitmStckList / sellPossQty 는 재고 숫자를 그대로 반환한다.
- ostkYn 은 일시품절 상품에서도 "0" 이다 (등록상품 표본 200건 전부 "0").
- 실제 판별 필드는 itemSellGbcd — "11" 이면 구매버튼이 '일시품절'(비활성).
  라이브 8건 대조: "11" 4건 전부 일시품절 / "00" 4건 전부 구매가능.

재고 숫자만 보고 판정하면 품절 상품이 마켓에 계속 노출돼 주문→발주불가 취소가 난다.
"""

from contextlib import asynccontextmanager
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.proxy.thehyundai_sourcing import TheHyundaiSourcingClient


class _Product:
    """오토튠이 넘기는 SambaCollectedProduct 최소 스텁."""

    def __init__(self):
        self.id = "cp_test"
        self.site_product_id = "40B0156585"
        self.source_url = "https://hi.thehyundai.com/product/40B0156585"
        self.options = [{"name": "JP9405/200", "price": 36350, "stock": 3}]
        self.sale_price = 56300.0
        self.sale_status = "in_stock"


def _detail(item_sell_gbcd: str) -> dict:
    """라이브 40B0156585 응답 발췌 — 일시품절인데 재고가 살아있는 실제 형태."""
    return {
        "slitmCd": "40B0156585",
        "slitmNm": "런팔콘 5 슈즈 JP9405 Clear Pink (170-210)",
        "itemSellGbcd": item_sell_gbcd,
        "ostkYn": "0",  # ★ 일시품절이어도 "0" 으로 내려온다
        "sellPossQty": 14,
        "stckGdYn": "0",
        "uitmCombYn": "1",
        "prcInfo": {"csmPrc": 47200, "sellPrc": 47200, "dcPrc": 36350, "maxDcPrc": 36350},
        "uitmAttrTypeList": [{"uitmAttrTypeNm": "색상"}, {"uitmAttrTypeNm": "사이즈"}],
        "uitmAttrList": [{"uitmAttrTypeNm": "색상", "uitmNm": "JP9405"}],
    }


_STCK_LIST = [
    {"uitmCd": "00004", "uitmTotNm": "JP9405/200", "sellPossQty": 3},
    {"uitmCd": "00005", "uitmTotNm": "JP9405/210", "sellPossQty": 3},
]


def _patch(monkeypatch, detail: dict):
    @asynccontextmanager
    async def _fake_client(self):
        yield None

    async def _fake_detail(self, client, slitm_cd):
        return detail

    async def _fake_stck(self, client, slitm_cd):
        return list(_STCK_LIST)

    async def _fake_bnft(self, client, slitm_cd):
        return {"aplyDcPrc": 36350}

    monkeypatch.setattr(TheHyundaiSourcingClient, "_client", _fake_client)
    monkeypatch.setattr(TheHyundaiSourcingClient, "_get_detail", _fake_detail)
    monkeypatch.setattr(TheHyundaiSourcingClient, "_get_uitm_stck_list", _fake_stck)
    monkeypatch.setattr(TheHyundaiSourcingClient, "_get_max_bnft_list", _fake_bnft)


@pytest.mark.asyncio
async def test_refresh_itemsellgbcd_11_은_재고가_있어도_품절(monkeypatch):
    """옵션 재고 3개가 살아있어도 itemSellGbcd=="11" 이면 sold_out 이어야 한다."""
    _patch(monkeypatch, _detail("11"))

    result = await TheHyundaiSourcingClient().refresh_product(_Product())

    assert result.new_sale_status == "sold_out"
    assert result.changed is True  # in_stock → sold_out 전환이 마켓에 전송돼야 함


@pytest.mark.asyncio
async def test_refresh_itemsellgbcd_00_은_정상_판매중(monkeypatch):
    """정상 판매 상품("00")을 품절로 오판하지 않는다."""
    _patch(monkeypatch, _detail("00"))

    result = await TheHyundaiSourcingClient().refresh_product(_Product())

    assert result.new_sale_status == "in_stock"


@pytest.mark.asyncio
async def test_refresh_ostkyn_1_은_기존대로_품절(monkeypatch):
    """기존 ostkYn 경로도 유지 (회귀 방지)."""
    d = _detail("00")
    d["ostkYn"] = "1"
    _patch(monkeypatch, d)

    result = await TheHyundaiSourcingClient().refresh_product(_Product())

    assert result.new_sale_status == "sold_out"


def test_build_detail_itemsellgbcd_11_은_품절표시():
    """수집·상세 경로도 동일 규칙 — isSoldOut True."""
    client = TheHyundaiSourcingClient()
    built = client._build_detail("40B0156585", _detail("11"), list(_STCK_LIST), {"aplyDcPrc": 36350})

    assert built["isSoldOut"] is True


def test_build_detail_itemsellgbcd_00_은_판매중():
    client = TheHyundaiSourcingClient()
    built = client._build_detail("40B0156585", _detail("00"), list(_STCK_LIST), {"aplyDcPrc": 36350})

    assert built["isSoldOut"] is False


@pytest.mark.asyncio
async def test_품절이면_옵션재고도_0으로_내린다(monkeypatch):
    """오토튠 '오삭제 방지' 가드를 통과하려면 옵션 재고가 0이어야 한다.

    가드(collector_autotune.py): sold_out 이어도 stock>0 이고 isSoldOut=False 인
    옵션이 하나라도 있으면 in_stock 으로 되돌린다 — ABC/무신사의 부분품절 오보고로
    멀쩡한 사이즈까지 통째 삭제되던 사고 방어층. 더현대는 일시품절이어도 재고 숫자를
    그대로 주므로, 옵션 재고를 0으로 내리지 않으면 이 가드에 걸려 품절 처리가 무효화된다.
    """
    _patch(monkeypatch, _detail("11"))

    result = await TheHyundaiSourcingClient().refresh_product(_Product())

    assert result.new_sale_status == "sold_out"
    assert result.new_options, "옵션 목록 자체는 유지돼야 한다(마켓 전송용)"
    assert all(o["stock"] == 0 for o in result.new_options)
    assert all(o["isSoldOut"] is True for o in result.new_options)

    # 가드 재현 — 살아있는 옵션이 없어야 품절 처리가 살아남는다
    has_live_opt = any(
        int(o.get("stock") or 0) > 0 and not o.get("isSoldOut", False)
        for o in result.new_options
    )
    assert has_live_opt is False


@pytest.mark.asyncio
async def test_정상판매는_옵션재고를_유지한다(monkeypatch):
    """"00" 상품의 재고를 0으로 깎아 멀쩡한 상품을 내리는 일이 없어야 한다."""
    _patch(monkeypatch, _detail("00"))

    result = await TheHyundaiSourcingClient().refresh_product(_Product())

    assert result.new_sale_status == "in_stock"
    assert [o["stock"] for o in result.new_options] == [3, 3]
    assert all(o["isSoldOut"] is False for o in result.new_options)
