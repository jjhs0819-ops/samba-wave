"""롯데홈 단일상품 등록 방지 가드 테스트 (2026-08-03).

SSG 수집 초기 옵션 파싱 누락분이 옵션 없이 단일상품으로 등록돼
"사이즈 선택 불가" 문의 폭주(노스페이스 2,224건). 옵션 0건 또는
전량 품절로 item_list가 비면 _transform_for_lottehome 이 ValueError 로
등록을 보류하는지 검증한다.
"""

from __future__ import annotations

import pytest

from backend.domain.samba.plugins.markets.lottehome import _transform_for_lottehome


def _product(options):
    return {
        "name": "노스페이스 눕시 다운 자켓 NJ1DP75A",
        "brand": "노스페이스",
        "sale_price": 250000,
        "images": ["https://example.com/a.jpg"],
        "options": options,
    }


def test_no_options_raises():
    with pytest.raises(ValueError, match="단일상품 등록 방지"):
        _transform_for_lottehome(_product([]), "cat1", {})


def test_all_soldout_options_raises():
    opts = [
        {"name": "M", "stock": 0, "isSoldOut": True},
        {"name": "L", "stock": 0, "isSoldOut": True},
    ]
    with pytest.raises(ValueError, match="단일상품 등록 방지"):
        _transform_for_lottehome(_product(opts), "cat1", {})


def test_healthy_options_build_item_list():
    opts = [
        {"name": "M", "stock": 3, "isSoldOut": False},
        {"name": "L", "stock": 2, "isSoldOut": False},
    ]
    data = _transform_for_lottehome(_product(opts), "cat1", {})
    assert data.get("item_mgmt_yn") == "Y"
    assert "M" in data.get("item_list", "") and "L" in data.get("item_list", "")
    assert "inv_qty" not in data
