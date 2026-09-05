"""송장 적재 무한재시도 차단 회귀 테스트 (2026-09-05).

배경(실측):
  ① 롯데온 회수송장 잡이 확장앱에서 120초를 통째로 기다리다 'timeout: content script 응답
     없음' 으로 죽는 것을 12분마다 영원히 반복. 주문 2건이 24시간에 54회 = 확장앱 89분 낭비.
     원인은 회수 종결된 옛 주문의 claim 페이지가 안 떠 content script 가 아예 주입되지 않는 것.
  ② 회수송장 적재 조건에 나이 제한이 없어, 회수가 영영 시작되지 않을 옛 반품(2026-05~08,
     22건 전량)을 계속 다시 넣고 있었다. 확장앱 수집 시도 1,902회 성공 0건.

조치: 신선도 컷(updated_at 기준) + 무응답 반복 주문 서킷브레이커.
"""

from __future__ import annotations

import inspect

from backend.domain.samba.tracking_sync import service as ts


def test_giveup_counts_only_timeouts() -> None:
    """무응답만 세야 한다 — 'no_tracking(미발송)' 은 정상 응답이라 같이 세면 멀쩡한 주문까지 포기한다."""
    src = inspect.getsource(ts._orders_with_repeated_timeouts)
    assert "error LIKE 'timeout:%'" in src
    assert "no_tracking" not in src, "미발송 응답을 실패로 세면 정상 주문까지 적재가 끊긴다"


def test_giveup_thresholds_are_sane() -> None:
    """너무 낮으면 일시 장애에 주문이 끊기고, 너무 높으면 낭비가 계속된다."""
    assert isinstance(ts._TIMEOUT_GIVEUP_THRESHOLD, int)
    assert 2 <= ts._TIMEOUT_GIVEUP_THRESHOLD <= 20
    assert isinstance(ts._TIMEOUT_GIVEUP_WINDOW_HOURS, int)
    # 창이 굴러가며 하루 몇 회는 재시도돼야 자가치유된다(영구 포기 금지).
    assert 1 <= ts._TIMEOUT_GIVEUP_WINDOW_HOURS <= 72


def test_giveup_never_blocks_the_main_path() -> None:
    """안전망 조회가 실패해도 적재는 평소대로 돌아야 한다."""
    src = inspect.getsource(ts._orders_with_repeated_timeouts)
    assert "except Exception" in src
    assert "return set()" in src, "실패 시 빈 집합을 못 돌려주면 적재 전체가 죽는다"


def test_giveup_short_circuits_on_empty_input() -> None:
    """후보가 없으면 DB 를 건드리지 않는다."""
    src = inspect.getsource(ts._orders_with_repeated_timeouts)
    body = src[src.index("if not order_ids"):]
    assert body.index("return set()") < body.index("get_write_session")


def test_bulk_tracking_enqueue_applies_giveup() -> None:
    """일반 송장 일괄 적재가 서킷브레이커를 실제로 적용해야 한다."""
    src = inspect.getsource(ts.enqueue_pending_orders)
    assert "_orders_with_repeated_timeouts(" in src
    assert "_stuck_orders" in src
    # 스킵이 카운트에 반영돼야 보고가 맞는다
    tail = src[src.index("if _o_id in _stuck_orders:"):]
    assert "skipped += 1" in tail and "continue" in tail


def test_return_enqueue_applies_giveup() -> None:
    """회수송장 일괄 적재도 동일 안전망을 적용해야 한다 — 이번 사고의 당사자."""
    src = inspect.getsource(ts.enqueue_return_pending)
    assert "_orders_with_repeated_timeouts(" in src
    tail = src[src.index("for oid in rows:"):]
    assert "if oid in _stuck:" in tail and "skipped += 1" in tail


def test_return_enqueue_has_freshness_cut() -> None:
    """회수가 영영 시작되지 않을 옛 반품을 계속 재큐잉하면 안 된다."""
    src = inspect.getsource(ts.enqueue_return_pending)
    assert "_RETURN_COLLECT_MAX_AGE_DAYS" in src
    assert "updated_at" in src, "created_at(주문일) 기준이면 반품 진행 중인 옛 주문이 잘려나간다"
    assert "coalesce" in src.lower(), "updated_at 이 비어도 안전하게 폴백해야 한다"


def test_return_freshness_window_is_sane() -> None:
    """회수 진행 기간을 덮되, 죽은 주문은 잘라야 한다."""
    assert isinstance(ts._RETURN_COLLECT_MAX_AGE_DAYS, int)
    assert 7 <= ts._RETURN_COLLECT_MAX_AGE_DAYS <= 60
