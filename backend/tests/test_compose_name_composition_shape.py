"""상품명 조합 배열이 손상된 형태로 저장돼 있어도 전송이 죽지 않아야 한다.

실측: market_name_compositions["11st"] 가 후보 배열의 배열
`[["{브랜드명}","{상품명}",...], [...], [...]]` 로 저장돼 있었고,
이 상태에서 _resolve_tag 의 `tag in tag_map` 이 unhashable type: 'list' 로 터져
11번가 전송이 상품명 조합 단계에서 통째로 실패했다.
(프론트 상세 패널도 같은 데이터로 `v.trim is not a function` 런타임 에러)
"""

from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.shipment.service import SambaShipmentService

PRODUCT = {
    "name": "울트라부스트 러닝화",
    "brand": "아디다스",
    "style_code": "OQ2DE112",
    "source_site": "musinsa",
    "site_product_id": "1234567",
}


def _rule(**kw):
    base = dict(
        name_composition=None,
        market_name_compositions=None,
        replacements=[],
        replace_mode="simultaneous",
        prefix="",
        suffix="",
        dedup_enabled=False,
        market_prefixes=None,
        market_suffixes=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_nested_market_composition_uses_first_candidate() -> None:
    service = SambaShipmentService(repo=None, session=None)  # type: ignore[arg-type]
    rule = _rule(
        name_composition=["{상품명}"],
        market_name_compositions={
            "11st": [
                ["{브랜드명}", "{상품명}", "{상품번호}"],
                ["{브랜드명}", "{상품명}"],
            ]
        },
    )

    result = service._compose_product_name(PRODUCT, rule, market_type="11st")

    # 첫 후보만 사용 — 후보를 합치면 브랜드/상품명이 중복된 이름이 마켓에 나간다
    assert result == "아디다스 울트라부스트 러닝화 1234567"


def test_non_string_entries_are_dropped() -> None:
    service = SambaShipmentService(repo=None, session=None)  # type: ignore[arg-type]
    rule = _rule(name_composition=["{브랜드명}", None, 123, {"tag": "x"}, "{상품명}"])

    result = service._compose_product_name(PRODUCT, rule)

    assert result == "아디다스 울트라부스트 러닝화"


def test_composition_of_only_non_strings_falls_back_to_raw_name() -> None:
    service = SambaShipmentService(repo=None, session=None)  # type: ignore[arg-type]
    rule = _rule(name_composition=[None, 123])

    result = service._compose_product_name(PRODUCT, rule)

    assert result == "울트라부스트 러닝화"


def test_normal_composition_unchanged() -> None:
    service = SambaShipmentService(repo=None, session=None)  # type: ignore[arg-type]
    rule = _rule(name_composition=["{상품명}", "매장정품", "{상품번호}"])

    result = service._compose_product_name(PRODUCT, rule)

    assert result == "울트라부스트 러닝화 매장정품 1234567"
