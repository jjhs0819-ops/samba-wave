"""POIZON 최저가 소싱처 가드 테스트 (2026-08-19).

같은 품번이 소싱처마다 별도상품으로 존재해 전부 등록하면 POIZON 중복 listing 이
된다. 그래서 최저가 소싱처(is_primary)만 등록한다 — 이건 **신규 등록** 억제용이다.

그런데 등록 직후 `_save_poison_match` 가 `product_id` 를 채우는 반면 `is_primary`
를 채우는 코드는 저장소 어디에도 없다(운영 라이브 입찰 355건 전량 키 없음).
그 결과 "product_id 있음 + is_primary 아님" = 영구 스킵이 되어, 한 번 등록된
상품은 오토튠이 가격·재고를 다시는 반영하지 못했다(오버셀/역마진 노출).

→ 이미 살아있는 입찰(biddingNo)이 있으면 가드를 적용하지 않는다.
"""

from __future__ import annotations

from backend.domain.samba.plugins.markets.poison import (
    has_live_bidding,
    should_skip_non_primary,
)


# ── 라이브 입찰 판정 ────────────────────────────────────────────
def test_biddingNo가_있으면_라이브_입찰이다():
    assert has_live_bidding({"sizes": {"275": {"biddingNo": "1512200348972366"}}})


def test_취소표시된_사이즈는_라이브가_아니다():
    assert not has_live_bidding(
        {"sizes": {"275": {"biddingNo": "1512", "status": "cancelled"}}}
    )


def test_biddingNo가_비었으면_라이브가_아니다():
    assert not has_live_bidding({"sizes": {"275": {"globalSkuId": 106406}}})
    assert not has_live_bidding({"sizes": {}})
    assert not has_live_bidding(None)


def test_일부_사이즈만_살아있어도_라이브다():
    assert has_live_bidding(
        {
            "sizes": {
                "270": {"biddingNo": "1512", "status": "cancelled"},
                "275": {"biddingNo": "1513"},
            }
        }
    )


# ── 가드 판정 ──────────────────────────────────────────────────
def test_기등록분은_primary가_아니어도_통과한다():
    """운영 355건 재현 — product_id 있음, is_primary 키 없음, 입찰 살아있음."""
    assert not should_skip_non_primary(
        {
            "product_id": "107361-04",
            "sizes": {"275": {"biddingNo": "151220034897236625", "price": 118000}},
        }
    )


def test_입찰이_없는_비primary_신규건은_스킵한다():
    assert should_skip_non_primary({"product_id": "107361-04", "sizes": {}})


def test_primary면_당연히_통과한다():
    assert not should_skip_non_primary(
        {"product_id": "107361-04", "is_primary": True, "sizes": {}}
    )


def test_아직_매칭_안된_상품은_가드_대상이_아니다():
    assert not should_skip_non_primary({"product_id": "", "sizes": {}})
    assert not should_skip_non_primary(None)


def test_취소된_입찰만_남았으면_비primary_신규로_보고_스킵한다():
    assert should_skip_non_primary(
        {
            "product_id": "107361-04",
            "sizes": {"275": {"biddingNo": "1512", "status": "cancelled"}},
        }
    )
