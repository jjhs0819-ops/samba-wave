"""패션플러스 카테고리 시드 존재 확인."""

from backend.domain.samba.category import rules


def test_패션플러스_시드가_등록되어_있다():
    assert "fashionplus" in rules.MARKET_CATEGORIES
    assert len(rules.MARKET_CATEGORIES["fashionplus"]) >= 5


def test_기존_마켓_시드는_그대로():
    """시드 추가가 기존 마켓을 건드리지 않았는지 확인."""
    assert "poison" in rules.MARKET_CATEGORIES
    assert "playauto" in rules.MARKET_CATEGORIES
