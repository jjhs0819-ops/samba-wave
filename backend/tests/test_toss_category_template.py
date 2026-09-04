"""토스 카테고리 제약 템플릿 반영 검증.

라이브 실측(36323 여성 바람막이 점퍼): 판매옵션 key 가 카테고리마다 정해져
있다 — "색상" / "패션의류/잡화 사이즈" / "수량". 우리가 임의로 "사이즈" 를
보내면 카테고리 규격과 어긋난다. 고시 코드도 카테고리별 허용목록
(productNoticeInfoTemplateTypes)이 따로 있다.
"""

from backend.domain.samba.proxy.toss import (
    TossClient,
    build_sale_options,
    pick_notice_category_code,
    sales_option_keys,
)

TEMPLATE = {
    "categorySalesOptions": [
        {"key": "색상"},
        {"key": "패션의류/잡화 사이즈"},
        {"key": "수량"},
    ],
    "productNoticeInfoTemplateTypes": ["CLOTHING", "SHOES", "BAG"],
}


def test_설정한_고시코드가_허용되면_그대로_쓴다():
    assert pick_notice_category_code(TEMPLATE, "SHOES") == "SHOES"


def test_허용되지_않는_고시코드는_의류로_대체한다():
    assert pick_notice_category_code(TEMPLATE, "FURNITURE") == "CLOTHING"


def test_의류도_없으면_허용목록_첫번째를_쓴다():
    t = {"productNoticeInfoTemplateTypes": ["FURNITURE", "ETC_GOODS"]}
    assert pick_notice_category_code(t, "SHOES") == "FURNITURE"


def test_템플릿의_판매옵션_키를_뽑는다():
    assert sales_option_keys(TEMPLATE) == ["색상", "패션의류/잡화 사이즈", "수량"]


def test_모든_필수_판매옵션을_채운다():
    """★라이브 실측★ 템플릿의 판매옵션은 전부 필수 — 하나라도 빠지면 거부된다."""
    opts = build_sale_options(
        ["색상", "패션의류/잡화 사이즈", "수량"],
        {"color": "다크 올리브"},
        "M",
    )
    assert opts == [
        {"groupName": "색상", "valueName": "다크 올리브"},
        {"groupName": "패션의류/잡화 사이즈", "valueName": "M"},
        {"groupName": "수량", "valueName": "1개"},
    ]


def test_색상이_없으면_단일_색상으로_채운다():
    opts = build_sale_options(["색상"], {}, "M")
    assert opts == [{"groupName": "색상", "valueName": "단일 색상"}]


def test_모르는_옵션키는_상세페이지_참조로_채운다():
    opts = build_sale_options(["원산지"], {}, "M")
    assert opts == [{"groupName": "원산지", "valueName": "상세페이지 참조"}]


def test_변환은_템플릿_판매옵션을_모두_싣는다():
    payload = TossClient.transform_product(
        {
            "name": "재킷",
            "sale_price": 1000,
            "color": "블랙",
            "options": [{"name": "M"}],
        },
        "36323",
        {"deliveryLocationId": 1, "exchangeRefundLocationId": 2},
        sales_option_keys=["색상", "패션의류/잡화 사이즈", "수량"],
    )
    assert payload["stocks"][0]["options"] == [
        {"groupName": "색상", "valueName": "블랙"},
        {"groupName": "패션의류/잡화 사이즈", "valueName": "M"},
        {"groupName": "수량", "valueName": "1개"},
    ]


# ── 택1(one-of) 그룹 ────────────────────────────────────────────
# 라이브 실측(34859 남성 반소매): '(택1) 색상' 과 '(택1) 색상/디자인' 이
# isOneOfRequiredGroup=True 로 함께 온다. 둘 다 실으면 토스가
# "택1 옵션은 한 가지만 쓸 수 있어요." 로 등록을 거부한다.

ONE_OF_TEMPLATE = {
    "categorySalesOptions": [
        {"key": "(택1) 색상", "isOneOfRequiredGroup": True},
        {"key": "(택1) 색상/디자인", "isOneOfRequiredGroup": True},
        {"key": "패션의류/잡화 사이즈", "isOneOfRequiredGroup": False},
        {"key": "수량", "isOneOfRequiredGroup": False},
    ],
    "productNoticeInfoTemplateTypes": ["CLOTHING"],
}


def test_택1_옵션은_하나만_싣는다():
    keys = sales_option_keys(ONE_OF_TEMPLATE)
    assert [k for k in keys if k.startswith("(택1)")] == ["(택1) 색상"]


def test_택1이_아닌_옵션은_모두_유지한다():
    keys = sales_option_keys(ONE_OF_TEMPLATE)
    assert "패션의류/잡화 사이즈" in keys and "수량" in keys
    assert len(keys) == 3


def test_택1_그룹의_색상값도_상품색상으로_채운다():
    opts = build_sale_options(["(택1) 색상"], {"color": "블랙"}, "M")
    assert opts == [{"groupName": "(택1) 색상", "valueName": "블랙"}]
