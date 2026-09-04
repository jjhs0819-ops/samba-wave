"""알파벳 후순위 사이트 아사(starvation) 회귀 차단 (2026-09-04).

배경: dequeue 정렬이 `site ASC` 라 THEHYUNDAI 는 항상 맨 뒤였다. 앞 사이트(ABCMART·
FASHIONPLUS·LOTTEON·MUSINSA) 잡이 매 사이클 새로 쌓이면 더현대 차례가 영영 오지 않는다.
실측 2026-09-04: 3시간 동안 더현대 송장 18건 중 dispatch 1건, 나머지는 pending 인 채
TTL 만료 → 더현대 송장 성공 0건. 다른 사이트는 같은 시간 36/36 정상 dispatch.
(cancel_order 는 2026-09-01 에 같은 이유로 최우선 티어로 이미 뺐다.)

조치: 일정 시간(STARVATION_MINUTES) 넘게 기다린 잡을 한 티어 위로 올린다.
티어 안에서는 기존 site→계정→FIFO 정렬 유지 — 같은 계정 연속 처리로 자동로그인 스왑을
줄이는 이점은 그대로다.
"""

from __future__ import annotations

import inspect
import re

from backend.domain.samba.proxy import sourcing_queue as sq


def _dequeue_source() -> str:
    return inspect.getsource(sq.SourcingQueue.get_next_job)


def test_starvation_tier_exists_before_site_ordering() -> None:
    """굶은 잡 티어가 site 정렬보다 앞에 와야 아사가 풀린다."""
    src = _dequeue_source()
    order_idx = src.index("ORDER BY")
    tail = src[order_idx:]
    starve_idx = tail.index("STARVATION_MINUTES")
    site_idx = tail.index("site ASC")
    assert starve_idx < site_idx, "굶은 잡 티어가 site 정렬보다 뒤에 있으면 아사가 그대로다"


def test_cancel_order_still_top_priority() -> None:
    """발주취소는 여전히 최우선(0티어) — 굶은 잡보다도 앞."""
    src = _dequeue_source()
    m = re.search(r"CASE WHEN job_type = 'cancel_order' THEN 0", src)
    assert m, "cancel_order 최우선 티어가 사라졌다"
    tail = src[m.end():]
    assert tail.index("THEN 1") < tail.index("ELSE 2"), "티어 번호 순서가 뒤집혔다"


def test_grouping_order_preserved() -> None:
    """티어 안에서는 site → 계정 → FIFO 순서가 그대로 유지돼야 한다.

    이 순서가 깨지면 같은 계정 잡이 흩어져 자동로그인 스왑이 폭증한다.
    """
    src = _dequeue_source()
    tail = src[src.index("ORDER BY"):]
    site_i = tail.index("site ASC")
    acc_i = tail.index("sourcingAccountId")
    fifo_i = tail.index("created_at ASC")
    assert site_i < acc_i < fifo_i


def test_starvation_minutes_is_sane() -> None:
    """너무 짧으면 그룹핑이 무의미해지고, 너무 길면 아사가 안 풀린다."""
    assert isinstance(sq.STARVATION_MINUTES, int)
    assert 5 <= sq.STARVATION_MINUTES <= 60
