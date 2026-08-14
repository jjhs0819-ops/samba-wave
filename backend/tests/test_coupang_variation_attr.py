"""쿠팡 옵션 속성 중복 방지 — 카테고리 필수 구매옵션 채움값 테스트.

2026-08-14 에잇세컨즈 실패 4건: S/M/L 3옵션 상품이 "중복된 옵션값"으로 전건 거절.
원인 — 카테고리 실제 사이즈 속성명("사이즈")이 우리가 보내는 이름
("패션의류/잡화 사이즈")과 달라, 쿠팡이 인정하는 쪽에는 전 아이템 동일한
상수 보충값이 들어가 3개 아이템이 같은 옵션으로 판정.
"""

from backend.domain.samba.proxy.coupang import _variation_fill_value


def test_size_like_names_use_item_size():
    for name in ["사이즈", "의류 사이즈", "패션의류/잡화 사이즈", "SIZE", "Size"]:
        assert _variation_fill_value(name, "M", "블랙") == "M"


def test_color_like_names_use_item_color():
    for name in ["색상", "컬러", "Color", "COLOR"]:
        assert _variation_fill_value(name, "M", "블랙") == "블랙"


def test_unrelated_names_return_empty_for_fallback():
    # 빈 문자열이면 호출부가 기존 상수 보충값으로 폴백한다
    assert _variation_fill_value("수량", "M", "블랙") == ""
    assert _variation_fill_value("제조국", "M", "블랙") == ""
    assert _variation_fill_value("", "M", "블랙") == ""


def test_missing_item_values_fall_back():
    assert _variation_fill_value("사이즈", "", "블랙") == ""
    assert _variation_fill_value("색상", "M", "") == ""


def test_size_priority_when_name_has_both_words():
    # "사이즈"가 먼저 매칭 — 색상/사이즈 복합명은 사이즈로 취급(변형축이 사이즈)
    assert _variation_fill_value("색상별 사이즈", "L", "화이트") == "L"
