"""송장(tracking) 잡 사이트 공평분배 회귀 차단 (2026-09-05).

배경: 2026-09-04 에 넣은 STARVATION_MINUTES 티어는 송장 아사를 못 푼다.
  ① 주문동기화 루프가 12~20분마다 pending 송장 잡을 전량 expire 시키고 새로 깐다
     (tracking_sync/service.py enqueue_pending_orders force=True) → 20분 굶기 전에 사라진다.
  ② 한 배치의 전 사이트 잡이 같은 1초 안에 생성된다 → 나이 티어로 올려도 전 사이트가
     동시에 승격하고, 티어 안에서 다시 site ASC 라 THEHYUNDAI 는 여전히 꼴찌다.
실측 2026-09-04 24h: 더현대 송장 dispatch 0건(잡 전량 pending 만료), 성공 0건.

조치: 최근 창 안에서 dispatch 건수가 적은 사이트부터 뽑는다(공평분배) + dispatch 즉시
메모리 카운트 +1 로 다음 폴링이 곧바로 다음 사이트를 고르게 한다.
"""

from __future__ import annotations

import inspect

from backend.domain.samba.proxy import sourcing_queue as sq

SITES = ["ABCMART", "FASHIONPLUS", "GSSHOP", "LOTTEON", "MUSINSA", "THEHYUNDAI"]


def _reset_cache() -> None:
    sq._tracking_prio_cache["at"] = 0.0
    sq._tracking_prio_cache["counts"] = {}


def test_least_dispatched_site_goes_first() -> None:
    """처리 적게 된 사이트가 먼저 — 알파벳 꼴찌라도 앞에 선다."""
    order = sq._tracking_site_order(
        {"ABCMART": 82, "LOTTEON": 411, "MUSINSA": 375, "THEHYUNDAI": 0}
    )
    assert order[0] == "THEHYUNDAI"
    assert order == ["THEHYUNDAI", "ABCMART", "MUSINSA", "LOTTEON"]


def test_tie_breaks_deterministically_by_site_name() -> None:
    """동률이면 사이트명 ASC — 순서가 흔들리면 계정 연속처리 이점이 깨진다."""
    counts = dict.fromkeys(SITES, 3)
    assert sq._tracking_site_order(counts) == sorted(SITES)


def test_empty_counts_is_safe() -> None:
    """집계가 비면 빈 리스트 — 호출부가 CASE 절을 통째로 생략해 SQL 이 깨지지 않는다."""
    assert sq._tracking_site_order({}) == []
    src = inspect.getsource(sq.SourcingQueue.get_next_job)
    assert "if _tsites:" in src, "빈 사이트 목록 가드가 사라지면 WHEN 없는 CASE 로 SQL 오류"


def test_dispatch_bump_rotates_to_next_site() -> None:
    """한 건 집어가면 즉시 다음 사이트로 넘어간다 (TTL 캐시가 같은 사이트를 반복 선택 못하게)."""
    _reset_cache()
    sq._tracking_prio_cache["counts"] = dict.fromkeys(SITES, 0)

    picked: list[str] = []
    for _ in range(len(SITES) * 3):
        first = sq._tracking_site_order(sq._tracking_prio_cache["counts"])[0]
        picked.append(first)
        sq._bump_tracking_dispatch(first)

    # 3바퀴 라운드로빈 — 모든 사이트가 정확히 3번씩
    for s in SITES:
        assert picked.count(s) == 3, f"{s} 배분 불균형: {picked}"
    _reset_cache()


def test_starved_site_catches_up_before_others_repeat() -> None:
    """실제 사고 상황 재현: 더현대만 0건, 나머지는 수백건 → 더현대가 먼저 밀린 만큼 따라잡는다."""
    _reset_cache()
    counts = {"ABCMART": 82, "FASHIONPLUS": 68, "LOTTEON": 411, "MUSINSA": 375, "THEHYUNDAI": 0}
    sq._tracking_prio_cache["counts"] = dict(counts)

    picked: list[str] = []
    for _ in range(6):  # 더현대 송장 잡은 배치당 6건 수준
        first = sq._tracking_site_order(sq._tracking_prio_cache["counts"])[0]
        picked.append(first)
        sq._bump_tracking_dispatch(first)

    assert picked == ["THEHYUNDAI"] * 6, f"굶은 사이트가 우선 처리되지 않음: {picked}"
    _reset_cache()


def test_bump_ignores_blank_site() -> None:
    """site 가 비면 카운트를 오염시키지 않는다."""
    _reset_cache()
    sq._bump_tracking_dispatch(None)
    sq._bump_tracking_dispatch("")
    sq._bump_tracking_dispatch("   ")
    assert sq._tracking_prio_cache["counts"] == {}
    _reset_cache()


def test_bump_is_case_insensitive() -> None:
    """site 케이싱이 섞여 있어도(ABCmart/ABCMART) 같은 사이트로 합산돼야 한다."""
    _reset_cache()
    sq._bump_tracking_dispatch("ABCmart")
    sq._bump_tracking_dispatch("ABCMART")
    assert sq._tracking_prio_cache["counts"] == {"ABCMART": 2}
    _reset_cache()


def test_fairshare_clause_applies_only_to_tracking() -> None:
    """공평분배는 송장 잡에만 — 가격수집(detail) 정렬을 건드리면 데몬 처리량이 흔들린다."""
    src = inspect.getsource(sq.SourcingQueue.get_next_job)
    assert "CASE WHEN job_type = 'tracking' " in src
    order_tail = src[src.index('f"ORDER BY "'):]
    assert order_tail.index("_tracking_prio_sql") < order_tail.index("site ASC NULLS LAST"), (
        "공평분배 절이 site ASC 뒤에 있으면 알파벳 정렬이 그대로 이겨 아사가 안 풀린다"
    )


def test_dispatch_bump_is_wired_into_dequeue() -> None:
    """dequeue 가 실제로 카운트를 올려야 한다 — 안 올리면 TTL 20초 동안 한 사이트가 독식."""
    src = inspect.getsource(sq.SourcingQueue.get_next_job)
    assert "_bump_tracking_dispatch(" in src
    assert "site, job_type FROM samba_sourcing_job" in src, "site/job_type 를 SELECT 해야 bump 가능"
