"""11번가 옵션가 base(colOptPrice) 계산 회귀 테스트.

11번가는 옵션가를 절대가격이 아니라 base 대비 추가금으로 받고,
추가금 0원인 옵션이 최소 1개 없으면 등록을 거부한다(500).
활성 옵션이 없을 때 base 가 0 으로 떨어지면 전 옵션에 상품가 전액이
추가금으로 붙어 그 거부에 걸린다.
"""

import re

from backend.domain.samba.proxy.elevenst import _build_elevenst_option_xml


def _opt_prices(xml: str) -> list[int]:
    """ProductOption 안의 colOptPrice 만 뽑는다(루트옵션 축 정의 포함)."""
    return [int(m) for m in re.findall(r"<colOptPrice>(\d+)</colOptPrice>", xml)]


def test_활성옵션_있으면_최저가가_base():
    options = [
        {"name": "230", "price": 26000, "stock": 3},
        {"name": "240", "price": 29000, "stock": 1},
    ]
    xml = _build_elevenst_option_xml(options, 0, None)
    assert _opt_prices(xml) == [0, 3000]


def test_전량_품절이어도_0원_옵션이_남는다():
    """실측 회귀: 하바이아나스 슬라이드 클래식(29,500) — 전 옵션 재고 0."""
    options = [
        {"name": s, "price": 29500, "stock": 0} for s in ("230", "240", "250", "270")
    ]
    xml = _build_elevenst_option_xml(options, 0, None)
    prices = _opt_prices(xml)
    assert prices == [0, 0, 0, 0], prices
    # 재고 0 이므로 판매는 막혀 있어야 한다
    assert xml.count("<useYn>N</useYn>") == 4


def test_품절옵션만_남아도_가격차는_유지된다():
    options = [
        {"name": "230", "price": 26000, "stock": 0},
        {"name": "240", "price": 31000, "stock": 0},
    ]
    xml = _build_elevenst_option_xml(options, 0, None)
    assert _opt_prices(xml) == [0, 5000]


def test_2D_멀티옵션도_동일_폴백():
    options = [
        {"name": "블랙 / 230", "price": 44100, "stock": 0},
        {"name": "블랙 / 240", "price": 44100, "stock": 0},
    ]
    xml = _build_elevenst_option_xml(options, 0, ["색상", "사이즈"])
    ext = xml.split("<ProductOptionExt>", 1)[1]
    assert _opt_prices(ext) == [0, 0]


def test_가격이_전부_0이면_base도_0():
    """가격 정보가 없는 옵션 — 기존 동작(추가금 0) 유지."""
    options = [{"name": "FREE", "price": 0, "stock": 5}]
    xml = _build_elevenst_option_xml(options, 0, None)
    assert _opt_prices(xml) == [0]
