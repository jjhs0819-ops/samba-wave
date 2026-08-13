"""전량품절 신규등록 보류 가드 — available_stock 판정 테스트.

2026-08-13 쿠팡 에잇세컨즈 실측: 재고변동 자동전송이 품절 이벤트를 미등록 상품의
신규등록으로 둔갑시켜 재고 0짜리 상품이 마켓에 깔리던 문제.
"""

from backend.domain.samba.shipment.service import available_stock


def test_all_soldout_camelcase():
    opts = [
        {"name": "S", "stock": 0, "isSoldOut": True},
        {"name": "M", "stock": 0, "isSoldOut": True},
    ]
    assert available_stock(opts) == 0


def test_soldout_with_residual_stock_excluded():
    # isSoldOut=True인데 stock이 남아있는 레거시 행 — 품절이 우선
    opts = [{"name": "S", "stock": 7, "isSoldOut": True}]
    assert available_stock(opts) == 0


def test_partial_stock_counts():
    opts = [
        {"name": "S", "stock": 3, "isSoldOut": False},
        {"name": "M", "stock": 0, "isSoldOut": True},
    ]
    assert available_stock(opts) == 3


def test_snake_case_soldout_recognized():
    opts = [{"name": "S", "stock": 5, "is_sold_out": True}]
    assert available_stock(opts) == 0


def test_string_and_float_stock_values():
    opts = [
        {"name": "S", "stock": "5", "isSoldOut": False},
        {"name": "M", "stock": "3.0", "isSoldOut": False},
        {"name": "L", "stock": None, "isSoldOut": False},
        {"name": "XL", "stock": "abc", "isSoldOut": False},
    ]
    assert available_stock(opts) == 8


def test_empty_or_none_options():
    assert available_stock([]) == 0
    assert available_stock(None) == 0
    assert available_stock([None, "junk"]) == 0
