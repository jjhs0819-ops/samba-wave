"""플레이오토 상품명 특수문자 정제 테스트.

2026-08-14 현대H몰 실거부: "판매상품명에 특수문자 ';' 는 포함될 수 없습니다."
EMP 마스터명은 연결된 전 쇼핑몰로 그대로 내려가므로 마스터 단계에서 제거한다.
"""

from backend.domain.samba.proxy.playauto import sanitize_prod_name


def test_semicolon_replaced_with_space():
    assert sanitize_prod_name("나이키 신발;블랙") == "나이키 신발 블랙"


def test_apostrophe_deleted_not_split():
    # 공백 치환하면 "Levi s"로 쪼개져 브랜드명이 깨진다
    assert sanitize_prod_name("Levi's 데님") == "Levis 데님"
    assert sanitize_prod_name("Levi’s 데님") == "Levis 데님"


def test_quotes_deleted():
    assert sanitize_prod_name('"베스트" 상품') == "베스트 상품"


def test_separator_chars_replaced():
    assert sanitize_prod_name("A|B<C>D") == "A B C D"
    assert sanitize_prod_name("A\\B") == "A B"


def test_consecutive_spaces_collapsed():
    assert sanitize_prod_name("나이키;;;신발") == "나이키 신발"
    assert sanitize_prod_name("  앞뒤 공백  ") == "앞뒤 공백"


def test_normal_name_unchanged():
    # 허용 문자(&, +, -, /, 괄호, 대괄호)는 건드리지 않는다
    name = (
        "매장정품 에잇세컨즈 8SECONDS 356325CML4 [단독] 미디 데님쇼츠 (블랙)/S+M & 세트"
    )
    assert sanitize_prod_name(name) == name


def test_control_chars_removed():
    assert sanitize_prod_name("나이키\t신발\n블랙") == "나이키 신발 블랙"


def test_none_and_empty():
    assert sanitize_prod_name(None) == ""
    assert sanitize_prod_name("") == ""
