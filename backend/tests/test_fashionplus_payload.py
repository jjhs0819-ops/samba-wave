"""패션플러스 페이로드 조립·가격 정규화 검증."""

import pytest

from backend.domain.samba.plugins.markets.fashionplus_payload import (
    MAX_STOCK,
    build_goods_add,
    build_scm_option_upt,
    clamp_stock,
    normalize_prices,
    option_key,
)


def test_소비자가_없으면_판매가의_90퍼_역산():
    """Err-Upt-110: 소비자가는 판매가의 90% 이상이어야 한다."""
    sale, consumer = normalize_prices(10000)
    assert sale == 10000
    assert consumer >= 9000


def test_소비자가가_90퍼_미달이면_끌어올린다():
    sale, consumer = normalize_prices(10000, 5000)
    assert consumer >= sale * 0.9


def test_소비자가가_충분하면_그대로():
    assert normalize_prices(10000, 12000) == (10000, 12000)


def test_100원_미만은_전송제외():
    assert normalize_prices(99) is None


def test_0원과_음수도_전송제외():
    assert normalize_prices(0) is None
    assert normalize_prices(-500) is None


def test_소수점_판매가는_정수로():
    sale, _ = normalize_prices(10000.7)
    assert isinstance(sale, int)


@pytest.mark.parametrize(
    "given,expected", [(-5, 0), (0, 0), (50, 50), (200, 200), (9999, MAX_STOCK)]
)
def test_재고는_0에서_200으로_클램프(given, expected):
    assert clamp_stock(given) == expected


def test_옵션키는_색상_사이즈_조합():
    assert option_key({"color": "BLACK", "size": "270"}) == "BLACK|270"


def test_옵션키는_공백_제거하고_대문자():
    assert option_key({"color": " black ", "size": "270"}) == "BLACK|270"


def _product():
    return {
        "id": "p1",
        "site_product_id": "MU123",
        "name": "나이키 에어포스1",
        "sale_price": 89000,
        "source_price": 70000,
        "images": ["https://mirror.example/1.jpg", "https://mirror.example/2.jpg"],
        "detail_html": "<p>상세</p>",
        "brand": "나이키",
        "options": [
            {"color": "BLACK", "size": "270", "stock": 5},
            {"color": "BLACK", "size": "280", "stock": 999},
        ],
    }


def test_등록_페이로드_필수필드():
    body = build_goods_add(_product(), "1010", "5477", "SND01")
    for key in (
        "ItemNo", "ItemName", "DisplayItemName", "SalePrice", "ConsumerPrice",
        "BrandId", "Category1", "Description", "ImageURL1",
    ):
        assert body[key] not in (None, "")


def test_등록_페이로드_이미지는_최대_4장():
    product = _product()
    product["images"] = [f"https://m/{i}.jpg" for i in range(9)]
    body = build_goods_add(product, "1010", "5477", "SND01")
    assert body["ImageURL4"] == "https://m/3.jpg"
    assert "ImageURL5" not in body


def test_등록_페이로드_이미지가_없으면_거부():
    product = _product()
    product["images"] = []
    with pytest.raises(ValueError):
        build_goods_add(product, "1010", "5477", "SND01")


def test_등록_페이로드_브랜드ID_없으면_거부():
    with pytest.raises(ValueError):
        build_goods_add(_product(), "1010", "", "SND01")


def test_등록_페이로드_카테고리_없으면_거부():
    with pytest.raises(ValueError):
        build_goods_add(_product(), "", "5477", "SND01")


def test_등록_페이로드_100원_미만이면_거부():
    product = _product()
    product["sale_price"] = 50
    with pytest.raises(ValueError):
        build_goods_add(product, "1010", "5477", "SND01")


def test_옵션갱신_재고_클램프_적용():
    rows = build_scm_option_upt(
        "777",
        {"BLACK|270": 111, "BLACK|280": 222},
        _product()["options"],
        update_price=False,
    )
    by_opt = {r["OptID"]: r for r in rows}
    assert by_opt[111]["StockQty"] == 5
    assert by_opt[222]["StockQty"] == MAX_STOCK


def test_옵션갱신_가격미변경이면_플래그_0():
    rows = build_scm_option_upt(
        "777", {"BLACK|270": 111}, _product()["options"], update_price=False
    )
    assert rows[0]["IsOptionPriceUpdate"] == 0


def test_옵션갱신_OptID_없는_옵션은_건너뛴다():
    rows = build_scm_option_upt(
        "777", {"BLACK|270": 111}, _product()["options"], update_price=False
    )
    assert len(rows) == 1
