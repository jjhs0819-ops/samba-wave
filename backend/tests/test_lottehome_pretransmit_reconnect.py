"""롯데홈쇼핑 전송 전 유령 재연결 가드 단위 테스트.

검증 항목:
  ① 재연결: 판매진행(10) ∧ DB 미매핑 ∧ 이름 끝 토큰 == site_product_id 정확일치
  ② 품절(20)/중단(30) 리스팅은 재연결하지 않음 (이득 없음)
  ③ 이미 매핑된 goods_no(보호셋)는 유령 후보에서 제외
  ④ 같은 상품에 판매진행 리스팅 2개+ → blocked (신규등록 시 3개째 방지)
  ⑤ 같은 site_product_id 상품 2개+ → 모두 blocked (오연결 방지)
  ⑥ 덤프에 없는 상품은 재연결도 차단도 안 함 (부분집합 — 신규등록 진행)
  ⑦ 이름 끝에 토큰 없는 리스팅은 매칭 불가 (유사도 매칭 금지)
  ⑧ LOTTEHOME_PRETRANSMIT_RECONNECT=0 이면 가드 비활성

reconnect_before_transmit 은 DB/마켓 IO 를 포함하므로 순수 매칭 함수
match_ghost_listings 를 직접 검증한다 (reconciler 테스트와 같은 접근).
"""

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from backend.domain.samba.shipment.lottehome_reconnect import (  # noqa: E402
    _enabled,
    match_ghost_listings,
)


def test_reconnects_selling_ghost_by_trailing_token():
    """① 판매진행 + 미매핑 + 토큰 정확일치 → 재연결."""
    dump = {
        "3373000001": ("10", "매장정품 에잇세컨즈 8SECONDS 셔츠 4238394"),
    }
    reconnect, blocked = match_ghost_listings(
        [("cp_A", "4238394")], dump, db_gnos=set()
    )
    assert reconnect == {"cp_A": "3373000001"}
    assert blocked == set()


def test_non_selling_listing_not_reconnected():
    """② 품절/중단 리스팅은 재연결 대상 아님."""
    dump = {
        "3373000001": ("20", "셔츠 4238394"),
        "3373000002": ("30", "바지 5555555"),
    }
    reconnect, blocked = match_ghost_listings(
        [("cp_A", "4238394"), ("cp_B", "5555555")], dump, db_gnos=set()
    )
    assert reconnect == {}
    assert blocked == set()


def test_mapped_goods_no_excluded_from_ghost_pool():
    """③ 이미 매핑된 goods_no 는 유령 후보가 아니다."""
    dump = {"3373000001": ("10", "셔츠 4238394")}
    reconnect, blocked = match_ghost_listings(
        [("cp_A", "4238394")], dump, db_gnos={"3373000001"}
    )
    assert reconnect == {}
    assert blocked == set()


def test_multiple_selling_listings_block_product():
    """④ 판매진행 리스팅 2개 매칭 = 마켓 중복 → 재연결/신규등록 모두 차단."""
    dump = {
        "3373000001": ("10", "셔츠 4238394"),
        "3373000002": ("10", "셔츠 리뉴얼 4238394"),
    }
    reconnect, blocked = match_ghost_listings(
        [("cp_A", "4238394")], dump, db_gnos=set()
    )
    assert reconnect == {}
    assert blocked == {"cp_A"}


def test_duplicate_spid_products_all_blocked():
    """⑤ 같은 site_product_id 상품 2개+ → 오연결 위험, 모두 차단."""
    dump = {"3373000001": ("10", "셔츠 4238394")}
    reconnect, blocked = match_ghost_listings(
        [("cp_A", "4238394"), ("cp_B", "4238394")], dump, db_gnos=set()
    )
    assert reconnect == {}
    assert blocked == {"cp_A", "cp_B"}


def test_absent_from_dump_passes_through():
    """⑥ 덤프에 매칭 리스팅 없음 → 재연결도 차단도 없음 (신규등록 진행)."""
    dump = {"3373000001": ("10", "다른 상품 9999999")}
    reconnect, blocked = match_ghost_listings(
        [("cp_A", "4238394")], dump, db_gnos=set()
    )
    assert reconnect == {}
    assert blocked == set()


def test_name_without_trailing_token_not_matched():
    """⑦ 이름 끝 토큰 없으면 매칭 불가 — 유사도 매칭은 하지 않는다."""
    dump = {"3373000001": ("10", "매장정품 에잇세컨즈 멀티 체크 반소매")}
    reconnect, blocked = match_ghost_listings(
        [("cp_A", "4238394")], dump, db_gnos=set()
    )
    assert reconnect == {}
    assert blocked == set()


def test_short_token_ignored():
    """⑦' 5자리 미만 숫자는 토큰이 아니다 (사이즈 등 오인 방지)."""
    dump = {"3373000001": ("10", "리넨 셔츠 9500")}
    reconnect, blocked = match_ghost_listings(
        [("cp_A", "9500")], dump, db_gnos=set()
    )
    assert reconnect == {}
    assert blocked == set()


def test_env_flag_disables_guard(monkeypatch):
    """⑧ LOTTEHOME_PRETRANSMIT_RECONNECT=0 → 비활성."""
    monkeypatch.setenv("LOTTEHOME_PRETRANSMIT_RECONNECT", "0")
    assert _enabled() is False
    monkeypatch.setenv("LOTTEHOME_PRETRANSMIT_RECONNECT", "1")
    assert _enabled() is True
    monkeypatch.delenv("LOTTEHOME_PRETRANSMIT_RECONNECT")
    assert _enabled() is True  # 기본 ON
