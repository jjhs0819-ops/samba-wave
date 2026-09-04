"""토스쇼핑 상품 등록 페이로드 변환 검증.

토스 상품 등록(POST /api/v3/shopping-fep/products/v2)은 필수 필드가 많고,
누락되면 HTTP 200 + resultType=FAIL 로 조용히 거부된다(라이브 실측:
빈 바디 전송 시 INVALID_REQUEST {"name":"필수 값이 누락되었습니다."}).
그래서 변환 단계에서 필수 구조를 고정해둔다.
"""

from backend.domain.samba.proxy.toss import TossClient

SETTINGS = {
    "deliveryLocationId": 1531077,
    "exchangeRefundLocationId": 1531079,
    "deliveryFee": 3000,
    "freeConditionAmount": 50000,
    "jejuFee": 3000,
    "returnFee": 5000,
    "exchangeFee": 10000,
    "stockQuantity": 99,
    "noticeCategoryCode": "SHOES",
}

PRODUCT = {
    "name": "나이키 에어포스1 07 화이트",
    "brand": "나이키",
    "sale_price": 129000,
    "images": [
        "https://img.example.com/main.jpg",
        "https://img.example.com/sub1.jpg",
    ],
    "detail_html": "<p>상세설명</p>",
    "options": [
        {"name": "250", "stock": 5, "isSoldOut": False},
        {"name": "260", "stock": 0, "isSoldOut": True},
    ],
    "seo_keywords": ["나이키", "에어포스", "운동화"],
}


def _payload(product=None, settings=None, category_id="12345"):
    return TossClient.transform_product(
        product if product is not None else PRODUCT,
        category_id,
        settings if settings is not None else SETTINGS,
    )


def test_필수_최상위_필드가_모두_있다():
    p = _payload()
    필수 = {
        "name",
        "categoryId",
        "stocks",
        "images",
        "exposure",
        "isTaxFree",
        "deliveryPolicy",
        "exchangeReturnPolicy",
        "notice",
    }
    assert 필수 <= set(p)


def test_상품명은_100자로_자른다():
    p = _payload({**PRODUCT, "name": "가" * 150})
    assert len(p["name"]) == 100


def test_대표가격_stock은_정확히_하나다():
    """isMainPrice 가 없거나 둘 이상이면 토스가 등록을 거부한다."""
    stocks = _payload()["stocks"]
    assert sum(1 for s in stocks if s["isMainPrice"]) == 1


def test_옵션마다_stock을_만들고_groupName을_붙인다():
    stocks = _payload()["stocks"]
    assert len(stocks) == 2
    assert stocks[0]["options"] == [{"groupName": "사이즈", "valueName": "250"}]
    assert stocks[1]["options"] == [{"groupName": "사이즈", "valueName": "260"}]


def test_품절옵션은_재고0에_품절표시한다():
    품절 = _payload()["stocks"][1]
    assert 품절["isSoldOut"] is True
    assert 품절["remainingCount"] == 0


def test_재고는_계정설정_상한을_넘지_않는다():
    stocks = _payload({**PRODUCT, "options": [{"name": "250", "stock": 9999}]})
    assert stocks["stocks"][0]["remainingCount"] == 99


def test_옵션이_없으면_단일_stock을_만든다():
    p = _payload({**PRODUCT, "options": []})
    assert len(p["stocks"]) == 1
    assert p["stocks"][0]["isMainPrice"] is True
    assert p["stocks"][0]["salePrice"] == 129000


def test_판매가는_계산된_최종가를_우선한다():
    p = _payload({**PRODUCT, "_final_sale_price": 150000})
    assert all(s["salePrice"] == 150000 for s in p["stocks"])


def test_첫이미지는_항상_썸네일이다():
    imgs = _payload()["images"]
    assert imgs[0]["type"] == "THUMBNAIL"
    assert imgs[0]["url"] == "https://img.example.com/main.jpg"


def test_상세HTML은_url이_아니라_html필드로_보낸다():
    """★함정★ DESCRIPTION_HTML 은 url 이 아닌 html 필드에 실어야 한다."""
    html = [i for i in _payload()["images"] if i["type"] == "DESCRIPTION_HTML"]
    assert len(html) == 1
    assert html[0]["html"] == "<p>상세설명</p>"


def test_상세HTML이_있으면_설명이미지는_보내지_않는다():
    """★라이브 실측★ 토스는 '상세 이미지 또는 html 둘 중 하나만' 받는다."""
    types = [i["type"] for i in _payload()["images"]]
    assert types == ["THUMBNAIL", "DESCRIPTION_HTML"]


def test_상세HTML이_없으면_설명이미지를_보낸다():
    p = {**PRODUCT}
    p.pop("detail_html")
    types = [i["type"] for i in _payload(p)["images"]]
    assert types == ["THUMBNAIL", "DESCRIPTION"]


def test_검색키워드는_10글자_넘으면_버린다():
    p = _payload(
        {**PRODUCT, "seo_keywords": ["운동화", "열글자를넘어가는아주긴키워드"]}
    )
    assert p["exposure"]["searchKeywords"] == ["운동화"]


def test_배송정책은_계정설정_출고지를_쓴다():
    d = _payload()["deliveryPolicy"]
    assert d["deliveryLocationId"] == 1531077
    assert d["deliveryFeeType"] == "CONDITIONALLY_FREE"
    assert d["deliveryFee"] == 3000
    assert d["minimumPurchasePrice"] == 50000
    assert d["jejuDeliveryFee"] == 3000


def test_배송비가_0이면_무료배송이다():
    d = _payload(settings={**SETTINGS, "deliveryFee": 0})["deliveryPolicy"]
    assert d["deliveryFeeType"] == "FREE"


def test_교환반품정책은_계정설정_반품지를_쓴다():
    e = _payload()["exchangeReturnPolicy"]
    assert e["exchangeRefundLocationId"] == 1531079
    assert e["refundOneWayDeliveryFee"] == 5000
    assert e["exchangeRoundTripDeliveryFee"] == 10000


def test_고시는_계정설정_카테고리코드를_쓴다():
    assert _payload()["notice"]["categoryCode"] == "SHOES"
