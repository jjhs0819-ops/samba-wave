"""헤드리스 데몬 풀 사이트별 owner 선택 헬퍼.

(2026-05-25 정리) 단일 룰: PC 체크박스(`_pc_allowed_sites`) 만 본다.
env fallback / 자동 정책 모두 폐기. 매칭 없으면 무조건 None → 잡 발행 skip.
"""

from __future__ import annotations

import time
from threading import Lock

_rr_counters: dict[str, int] = {}
_rr_lock = Lock()


def pick_daemon_owner(site: str, settings_obj: object | None = None) -> str | None:
    """site 를 체크한 데몬 device 1개를 round-robin 선택 (prefix='samba-daemon-')."""
    return _pick_owner_with_prefix(site, daemon_only=True)


def pick_extension_owner(site: str) -> str | None:
    """site 를 체크한 확장앱 device 1개를 round-robin 선택 (prefix 무관, samba-daemon- 제외)."""
    return _pick_owner_with_prefix(site, daemon_only=False)


def pick_any_owner(site: str) -> str | None:
    """site 를 체크한 PC 1개 — 데몬/확장앱 무관. PC 체크박스 단일 룰."""
    d = pick_daemon_owner(site)
    if d:
        return d
    return pick_extension_owner(site)


def _pick_owner_with_prefix(site: str, daemon_only: bool) -> str | None:
    pool: list[str] = []
    try:
        from backend.api.v1.routers.samba.collector_autotune import (
            _pc_allowed_sites,
            _pc_last_seen,
            _site_block_backoff_until,
        )

        now = time.time()
        _site_u = (site or "").upper()
        for dev, sites in _pc_allowed_sites.items():
            is_daemon = dev.startswith("samba-daemon-")
            if daemon_only and not is_daemon:
                continue
            if (not daemon_only) and is_daemon:
                continue
            if _site_u not in {s.upper() for s in sites}:
                continue
            last = _pc_last_seen.get(dev, 0)
            # 데몬은 long process_job(SSG extract_pdp 50s) 동안 폴링 못 함 →
            # 60s strict TTL 위반으로 풀에서 빠져 "데몬 미등록" 회귀.
            # 데몬은 별도 heartbeat 15s 로 last_seen 갱신하므로 180s 까지 허용.
            # 확장앱은 인터넷 OFF 빠르게 탐지 위해 60s 유지.
            ttl = 180.0 if daemon_only else 60.0
            if now - last > ttl:
                continue
            # PC별 차단 백오프 중인 device 는 풀에서 제외 — 잡이 건강한 PC로만
            # 라우팅돼 사이트 전체가 안 멈춘다 (2026-08-02 SSG PC별 격리)
            if _site_block_backoff_until.get(f"{_site_u}|{dev}", 0.0) > now:
                continue
            # [2026-08-04] 확장앱은 "그 사이트로 실제 폴링했는지"까지 확인.
            # _pc_last_seen 은 pc-allowed-sites POST 같은 하트비트로도 갱신돼,
            # 해당 사이트 폴링을 멈춘 PC 도 살아있는 것처럼 보인다. 그 PC 를
            # owner 로 뽑으면 잡을 아무도 안 가져가 SITE_PRODUCT_TIMEOUT(SSG 150s)
            # 을 통째로 태우고 실패한다(실측 건당 200초+, 진행 0/13,279).
            # 폴링 기록이 아직 없는 초기 상태는 통과시켜 회귀를 만들지 않는다.
            if not daemon_only:
                # ruff formatter 가 상단 import 를 제거해 F821 을 유발하므로 로컬 import
                from backend.api.v1.routers.samba import (  # noqa: F811
                    collector_autotune as _ca,
                )

                _ps = _ca._pc_site_poll_seen.get((dev, _site_u))
                if _ps is not None and now - _ps > _ca.PC_SITE_POLL_TTL:
                    continue
            pool.append(dev)
        pool.sort()
    except Exception:
        pool = []

    if not pool:
        return None

    key = ("daemon:" if daemon_only else "ext:") + site
    with _rr_lock:
        idx = _rr_counters.get(key, 0) % len(pool)
        _rr_counters[key] = idx + 1
    return pool[idx]


def has_alive_daemon() -> bool:
    """살아있는 데몬(heartbeat 180s 이내) 1대라도 있나 — 오토튠 담당(_pc_allowed_sites) 무관.

    송장(tracking)은 가격수집(detail)과 달리 오토튠 사이트 분담과 무관해야 한다.
    데몬은 시작 시 모든 사이트를 active 로 올려 SSG/ABC/LOTTEON 로그인+송장조회가
    가능하므로, "이 사이트를 오토튠 담당으로 체크한 PC"가 아니라 "살아있는 데몬 아무나"가
    송장을 처리할 수 있어야 한다. pick_daemon_owner(=_pc_allowed_sites 기반)로 송장
    owner 를 박으면, SSG 오토튠 담당 PC가 0대이거나 그 PC 데몬이 죽으면 송장이 영영
    발행/처리 안 되는 버그가 생긴다(2026-06-01 확인). 이 함수는 그 발행 가드용.
    """
    try:
        import time

        from backend.api.v1.routers.samba.collector_autotune import _pc_last_seen

        now = time.time()
        for dev, last in _pc_last_seen.items():
            if dev.startswith("samba-daemon-") and now - last <= 180.0:
                return True
    except Exception:
        pass
    return False
