"""11번가 상품명 폴백 체인 회귀 테스트.

market_name_compositions 의 "후보 배열의 배열"은 손상이 아니라 폴백 체인이다.
_normalize_composition 이 이걸 평탄화하면 체인이 조용히 죽어 첫 후보가 99byte 를
넘겨도 그대로 나가고 뒤쪽 상품번호가 잘린다 — 실제로 한 번 그렇게 깨졌다.
"""

from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.shipment.service import SambaShipmentService

LONG = {
    "name": "슬림 스퀘어 글리터 네온 핑크 플립플랍 쪼리",
    "brand": "하바이아나스",
    "site_product_id": "3246537",
}
SHORT = {"name": "쪼리", "brand": "하바이아나스", "site_product_id": "3246537"}

CHAIN = [
    ["{브랜드명}", "{상품명}", "{상품번호}", "매장정품"],
    ["{브랜드명}", "{상품명}", "{상품번호}"],
    ["{브랜드명}", "{상품명}"],
]


def _rule():
    return SimpleNamespace(
        name_composition=["{상품명}"],
        market_name_compositions={"11st": CHAIN},
        replacements=[], replace_mode="simultaneous", prefix="", suffix="",
        dedup_enabled=False, market_prefixes=None, market_suffixes=None,
    )


def test_짧으면_1단계():
    svc = SambaShipmentService(repo=None, session=None)  # type: ignore[arg-type]
    r = svc._compose_product_name(SHORT, _rule(), market_type="11st")
    assert r == "하바이아나스 쪼리 3246537 매장정품", r


def test_길면_한도내로_떨어진다():
    svc = SambaShipmentService(repo=None, session=None)  # type: ignore[arg-type]
    r = svc._compose_product_name(LONG, _rule(), market_type="11st")
    assert len(r.encode("utf-8")) <= 99, (len(r.encode("utf-8")), r)
    assert r.startswith("하바이아나스 "), r
    assert "매장정품" not in r, r
