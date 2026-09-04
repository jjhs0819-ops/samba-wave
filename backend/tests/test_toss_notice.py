"""토스쇼핑 정보제공 고시 자동 채움 검증.

고시(notice)는 등록 필수값이고, 항목 id 는 고시 카테고리코드별로 토스가
동적으로 내려준다(라이브 실측 SHOES = 8개 항목). 항목마다 content 가 비면
등록이 거부되므로 상품 필드 → 고시 문구 매핑을 고정한다.
"""

from backend.domain.samba.proxy.toss import build_notice_items

SHOES_ITEMS = [
    {
        "id": 45,
        "title": "1. 제품 주소재 (운동화인 경우에는 겉감, 안감을 구분하여 표시)",
    },
    {"id": 47, "title": "2. 색상"},
    {"id": 49, "title": "3. 치수"},
    {"id": 51, "title": "4. 제조자, 수입품의 경우 수입자를 함께 표기"},
    {"id": 53, "title": "5. 제조국"},
    {"id": 55, "title": "6. 취급시 주의사항"},
    {"id": 57, "title": "7. 품질보증기준"},
    {"id": 59, "title": "8. A/S 책임자와 전화번호"},
]

PRODUCT = {
    "name": "나이키 에어포스1",
    "brand": "나이키",
    "material": "가죽",
    "color": "화이트",
    "origin": "베트남",
    "manufacturer": "나이키코리아",
}
SETTINGS = {"asPhone": "010-1234-5678"}


def test_모든_항목에_id와_content가_채워진다():
    items = build_notice_items(SHOES_ITEMS, PRODUCT, SETTINGS)
    assert len(items) == len(SHOES_ITEMS)
    assert {i["id"] for i in items} == {45, 47, 49, 51, 53, 55, 57, 59}
    assert all(i["content"] for i in items)


def test_상품필드가_있으면_그_값을_쓴다():
    items = {
        i["id"]: i["content"]
        for i in build_notice_items(SHOES_ITEMS, PRODUCT, SETTINGS)
    }
    assert items[45] == "가죽"
    assert items[47] == "화이트"
    assert items[53] == "베트남"
    assert items[51] == "나이키코리아"


def test_AS전화는_계정설정을_쓴다():
    items = {
        i["id"]: i["content"]
        for i in build_notice_items(SHOES_ITEMS, PRODUCT, SETTINGS)
    }
    assert items[59] == "010-1234-5678"


def test_값이_없으면_상세페이지_참조로_채운다():
    items = {i["id"]: i["content"] for i in build_notice_items(SHOES_ITEMS, {}, {})}
    assert items[45] == "상세페이지 참조"
    assert items[47] == "상세페이지 참조"


def test_품질보증은_법령_문구를_쓴다():
    items = {i["id"]: i["content"] for i in build_notice_items(SHOES_ITEMS, {}, {})}
    assert "소비자분쟁해결기준" in items[57]


def test_content는_4000자를_넘지_않는다():
    long_product = {**PRODUCT, "material": "가" * 5000}
    items = {
        i["id"]: i["content"]
        for i in build_notice_items(SHOES_ITEMS, long_product, SETTINGS)
    }
    assert len(items[45]) == 4000
