"""패션플러스 페이로드 조립·가격 정규화 검증."""

import pytest

from backend.domain.samba.plugins.markets.fashionplus_payload import (
    MAX_STOCK,
    build_goods_add,
    build_scm_option_upt,
    clamp_stock,
    extract_consumer_price,
    has_uneven_option_price,
    normalize_prices,
    option_key,
)


def test_소비자가_없으면_판매가를_0_9로_나눠_역산():
    """하한은 ceil(판매가 / 0.9) — 정가(소비자가)는 판매가보다 싸면 안 된다."""
    sale, consumer = normalize_prices(10000)
    assert sale == 10000
    assert consumer == 11112  # ceil(10000 / 0.9)


def test_소비자가가_하한_미달이면_끌어올린다():
    sale, consumer = normalize_prices(10000, 5000)
    assert consumer >= sale
    assert consumer >= sale * 0.9  # 패플 제약 Err-Upt-110 도 자동 만족


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


@pytest.mark.parametrize("sale", [100, 8999, 10000, 89000, 1234567])
def test_정가는_항상_판매가_이상(sale):
    """정가 < 판매가는 말이 안 되는 값 — 어떤 판매가에도 성립해야 한다."""
    _, consumer = normalize_prices(sale)
    assert consumer >= sale


def test_정가입력은_original_price_우선():
    """수집 모델의 정가 필드는 original_price 다 (collector/model.py)."""
    assert extract_consumer_price({"original_price": 120000}) == 120000
    assert (
        extract_consumer_price({"original_price": 120000, "consumer_price": 90000})
        == 120000
    )


def test_정가입력_original_price_없으면_consumer_price_폴백():
    assert extract_consumer_price({"consumer_price": 90000}) == 90000
    assert extract_consumer_price({}) is None


def test_등록_페이로드가_original_price를_정가로_쓴다():
    product = _product()
    product["original_price"] = 150000
    body = build_goods_add(product, "1010", "5477", "SND01")
    assert body["ConsumerPrice"] == 150000


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


# --- 수정 라운드 1: 리뷰 지적 대응 테스트 ---


def test_옵션갱신_가격변경시_옵션가_0도_그대로_전송():
    """패플 공식 샘플상 OptPrice 0 은 적법한 값 — 있는 그대로 보낸다."""
    options = [{"color": "BLACK", "size": "270", "stock": 5, "option_price": 0}]
    rows = build_scm_option_upt("777", {"BLACK|270": 111}, options, update_price=True)
    assert rows[0]["OptPrice"] == 0
    assert rows[0]["IsOptionPriceUpdate"] == 1


def test_옵션갱신_가격변경인데_옵션가_키_없으면_제외():
    """값 없음을 0 으로 날조 금지 — 역마진 사고 방지."""
    rows = build_scm_option_upt(
        "777",
        {"BLACK|270": 111, "BLACK|280": 222},
        _product()["options"],
        update_price=True,
    )
    assert rows == []


def test_옵션갱신_가격변경인데_옵션가_해석불가면_제외():
    options = [{"color": "BLACK", "size": "270", "stock": 5, "option_price": "abc"}]
    rows = build_scm_option_upt("777", {"BLACK|270": 111}, options, update_price=True)
    assert rows == []


def test_옵션갱신_가격미변경이면_OptPrice_키_자체가_없음():
    rows = build_scm_option_upt(
        "777", {"BLACK|270": 111}, _product()["options"], update_price=False
    )
    assert "OptPrice" not in rows[0]


def test_옵션키_색상사이즈_모두_없으면_보조값으로_구분():
    """원사이즈 상품 — 서로 다른 옵션이 같은 키로 수렴하면 안 된다."""
    k1 = option_key({"name": "FREE-A"})
    k2 = option_key({"name": "FREE-B"})
    assert k1 and k2 and k1 != k2


def test_옵션키_보조값도_없으면_빈문자열():
    assert option_key({}) == ""


def test_옵션키_빈문자열은_매핑불가로_스킵():
    rows = build_scm_option_upt("777", {"": 111}, [{"stock": 5}], update_price=False)
    assert rows == []


def test_등록_페이로드_ItemNo_없으면_거부():
    product = _product()
    product["site_product_id"] = ""
    product["id"] = None
    with pytest.raises(ValueError):
        build_goods_add(product, "1010", "5477", "SND01")


def test_옵션갱신_스킵옵션_경고로그(caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        build_scm_option_upt(
            "777", {"BLACK|270": 111}, _product()["options"], update_price=False
        )
    assert "BLACK|280" in caplog.text


def test_옵션갱신_옵션가_제외도_경고로그(caplog):
    import logging

    options = [{"color": "BLACK", "size": "270", "stock": 5}]
    with caplog.at_level(logging.WARNING):
        build_scm_option_upt("777", {"BLACK|270": 111}, options, update_price=True)
    assert "BLACK|270" in caplog.text


def test_옵션갱신_OptID_0은_유효한_매핑():
    rows = build_scm_option_upt(
        "777", {"BLACK|270": 0}, _product()["options"], update_price=False
    )
    assert len(rows) == 1
    assert rows[0]["OptID"] == 0


# --- 최종 리뷰 F3: 옵션키 보조값 id 0 처리 ---


def test_옵션키_보조값_id_0은_유효():
    """정수 0 은 falsy 지만 유효한 식별자 — 빈 키로 버려지면 안 된다."""
    assert option_key({"id": 0}) == "0"


def test_옵션키_name이_있으면_id보다_우선():
    assert option_key({"name": "FREE", "id": 0}) == "FREE"


# --- 최종 리뷰 F7: 옵션가 불균일 상품 전송 제외 (설계서 §4.4-3) ---


def test_옵션가불균일_옵션_0개는_False():
    assert has_uneven_option_price([]) is False


def test_옵션가불균일_옵션_1개는_False():
    assert has_uneven_option_price([{"option_price": 1000}]) is False


def test_옵션가불균일_전부_같으면_False():
    options = [{"option_price": 500}, {"option_price": 500}, {"option_price": 500}]
    assert has_uneven_option_price(options) is False


def test_옵션가불균일_전부_0이면_False():
    options = [{"option_price": 0}, {"option_price": 0}]
    assert has_uneven_option_price(options) is False


def test_옵션가불균일_일부만_키_있고_나머지_같으면_False():
    options = [{"option_price": 0}, {}, {"option_price": 0}]
    assert has_uneven_option_price(options) is False


def test_옵션가불균일_서로_다르면_True():
    options = [{"option_price": 0}, {"option_price": 3000}]
    assert has_uneven_option_price(options) is True


def test_옵션가불균일_해석불가_값은_판정에서_제외():
    options = [{"option_price": "abc"}, {"option_price": 1000}]
    assert has_uneven_option_price(options) is False


def test_등록_페이로드_옵션가_불균일이면_거부():
    """옵션별 가격이 다른 상품은 역마진 위험 — 전송 자체를 막는다."""
    product = _product()
    product["options"] = [
        {"color": "BLACK", "size": "270", "stock": 5, "option_price": 0},
        {"color": "BLACK", "size": "280", "stock": 5, "option_price": 5000},
    ]
    with pytest.raises(ValueError, match="옵션별 가격이 달라"):
        build_goods_add(product, "1010", "5477", "SND01")
