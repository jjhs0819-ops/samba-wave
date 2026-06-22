"""적립금 라우팅 → 트리거 PC 바인딩 회귀 테스트 (2026-06-22).

배경(버그):
  적립(reward: 출석체크/리뷰)이 DAEMON_ONLY_JOB_SITES["reward"] 에 묶여 있어
  ABC마트/SSG/그랜드스테이지/롯데ON 적립 잡이 _reward_owner_override 에서
  트리거 PC(실행 누른 PC)에 바인딩되지 못하고 None 을 반환 → 기존 데몬/라운드로빈
  라우팅으로 새서, 그 PC엔 해당 마켓 로그인이 없어 "타 PC 4b7d 실패"로 끝났다.

  데몬(tools/lotteon_daemon/site_handlers.py)은 ABC/SSG 의 '가격수집(detail)·송장
  (tracking)'만 처리하고 적립은 전혀 안 한다(적립=확장앱 content-reward-*.js).
  즉 적립을 데몬전용으로 분류한 것 자체가 오분류였다. KREAM/무신사 적립은 데몬전용이
  아니라 트리거 PC 에서 정상 동작 → 같은 동작을 4사이트에도 적용.

수정:
  DAEMON_ONLY_JOB_SITES["reward"] = set() → 적립은 어떤 사이트도 데몬전용이 아님 →
  _reward_owner_override 가 트리거 device 를 owner 로 박아 "실행 누른 그 PC 에서만"
  실행한다(KREAM/무신사와 동일). detail/tracking/search/cancel 라우팅은 불변.
"""

from __future__ import annotations


# sourcing_account 를 테스트에서 단독 import 하면 dtos.user <-> domain.user.service 의
# 기존(사전) 순환 import 가 import 순서상 첫 시도에서 ImportError 를 낸다 — 앱 기동 시엔
# import 순서로 자연 해소되는 사전 이슈로, 본 적립 라우팅 수정과 무관. 첫 시도를 1회
# 워밍업으로 흘려보내면 모듈 그래프가 채워져 이후 import 가 정상 동작한다.
try:  # pragma: no cover
    import backend.api.v1.routers.samba.sourcing_account  # noqa: F401
except Exception:  # noqa: BLE001
    pass


# ── 1) 데몬전용 매트릭스: reward 만 비워지고 나머지는 그대로 ─────────────────


def test_reward_is_no_longer_daemon_only():
    """적립(reward)은 더 이상 데몬전용 사이트가 없다 → 트리거 PC 바인딩 가능."""
    from backend.domain.samba.proxy import sourcing_queue as sq

    assert sq._daemon_only_for_job("reward") == set(), (
        "reward 가 데몬전용으로 남아있으면 트리거 PC 바인딩이 안 됨"
    )


def test_detail_tracking_search_still_daemon_only():
    """가격수집/송장/검색은 ABC·SSG 데몬전용 유지 — 적립만 바꾼 것 확인(회귀 방지)."""
    from backend.domain.samba.proxy import sourcing_queue as sq

    for job_type in ("detail", "tracking", "search"):
        sites = {s.upper() for s in sq._daemon_only_for_job(job_type)}
        assert "ABCMART" in sites, f"{job_type} 데몬전용이 깨짐: {sites}"
        assert "SSG" in sites, f"{job_type} 데몬전용이 깨짐: {sites}"


# ── 2) _reward_owner_override: 적립 4사이트 모두 트리거 PC 에 바인딩 ──────────


def test_reward_binds_to_trigger_pc_for_all_four_sites():
    """ABC/SSG/그랜드/롯데ON 적립이 트리거 PC(device) 에 owner 바인딩된다(핵심 수정)."""
    from backend.api.v1.routers.samba.sourcing_account import _reward_owner_override

    for site in ("ABCmart", "SSG", "GrandStage", "LOTTEON"):
        assert _reward_owner_override(site, "ext-pc-4b7d") == "ext-pc-4b7d", (
            f"{site} 적립이 트리거 PC 에 바인딩되지 않음 — 다른 PC 로 샐 수 있음"
        )


def test_reward_owner_none_without_trigger_device():
    """트리거 device 없으면(자동 스케줄러) None → 기존 라운드로빈 유지."""
    from backend.api.v1.routers.samba.sourcing_account import _reward_owner_override

    assert _reward_owner_override("ABCmart", None) is None
    assert _reward_owner_override("ABCmart", "") is None


def test_reward_owner_none_for_daemon_trigger():
    """데몬 device(samba-daemon-*)가 트리거면 PC 바인딩 안 함 → None."""
    from backend.api.v1.routers.samba.sourcing_account import _reward_owner_override

    assert _reward_owner_override("ABCmart", "samba-daemon-xyz") is None


def test_existing_extension_reward_sites_still_bind():
    """기존에 잘 되던 KREAM/무신사/GS샵/네이버도 여전히 트리거 PC 바인딩(회귀 방지)."""
    from backend.api.v1.routers.samba.sourcing_account import _reward_owner_override

    for site in ("KREAM", "MUSINSA", "GSShop", "NAVERSTORE"):
        assert _reward_owner_override(site, "ext-pc-4b7d") == "ext-pc-4b7d"
