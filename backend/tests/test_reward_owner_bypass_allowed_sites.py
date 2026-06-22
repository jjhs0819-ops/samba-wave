"""적립금 PC바인딩 ↔ 오토튠 분담(allowed_sites) 충돌 회귀 테스트 (2026-06-17).

배경:
  적립금 PC바인딩(_reward_owner_override)은 KREAM/무신사/GSShop/NAVERSTORE 적립
  잡의 owner_device_id 를 트리거 PC 로 박는다. 그런데 get_next_job 의 site(분담)
  필터가 owner 박힌 잡에도 그대로 적용돼, 트리거 PC 의 오토튠 분담에 해당 사이트가
  없으면(KREAM 은 소싱처 체크박스 자체가 없어 분담에 넣을 방법도 없음) 잡이 영영
  dequeue 안 돼 'pending → 만료'로 죽었다 (병기사무실2 분담=[SSG], KREAM 적립 만료).

수정:
  site 필터에 owner 우회 절(OR owner_device_id = :device_id)을 추가 — owner 가 이미
  "이 PC 가 받는다"를 확정했으므로 분담 재적용은 모순. 수집 잡(owner 미박힘)은
  영향 없이 분담 그대로 유지.

방식:
  레포 tests/ 에 DB fixture 가 없어(기존 테스트도 DB stub) get_write_session 을
  mock 하여 생성되는 WHERE 절(SQL 구성)을 검증한다.
"""

from __future__ import annotations

import asyncio
import re


class _FakeResult:
    def fetchone(self):
        return None  # hasJob=False — SQL 구성만 검증, 실제 행 불필요


class _FakeSession:
    def __init__(self, captured):
        self._captured = captured

    async def execute(self, sql, params=None):
        self._captured["sql"] = str(sql)
        self._captured["params"] = params or {}
        return _FakeResult()

    async def commit(self):
        return None


class _FakeCtx:
    def __init__(self, captured):
        self._captured = captured

    async def __aenter__(self):
        return _FakeSession(self._captured)

    async def __aexit__(self, *exc):
        return False


def _run_get_next_job(monkeypatch, *, device_id, allowed_sites, ext_version="2.14.1"):
    from backend.domain.samba.proxy import sourcing_queue as sq

    captured: dict = {}
    monkeypatch.setattr(sq, "get_write_session", lambda: _FakeCtx(captured))

    async def _run():
        return await sq.SourcingQueue.get_next_job(
            device_id=device_id,
            allowed_sites=allowed_sites,
            ext_version=ext_version,
        )

    asyncio.run(_run())
    return captured


def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", sql)


def test_owner_bound_job_bypasses_allowed_sites_filter(monkeypatch):
    """owner=이 PC 잡은 분담에 사이트 없어도 dequeue 후보가 된다.

    회귀: 분담=[SSG] 인데 owner-bound KREAM 적립 잡(site=KREAM)이 site 필터에
    걸려 만료되던 문제. 수정 후 site 필터 조건에 owner 우회 절이 포함돼야 한다.
    """
    cap = _run_get_next_job(monkeypatch, device_id="ext-pc-A", allowed_sites=["SSG"])
    sql = _norm(cap["sql"])

    # site(분담) 필터 조건:
    #   (job_type IN (... 'store_metrics') OR owner_device_id = :device_id
    #                                       OR UPPER(site) IN (:site_0))
    assert "OR owner_device_id = :device_id OR UPPER(site) IN" in sql, (
        f"site 필터에 owner 우회 절이 없음:\n{sql}"
    )
    assert cap["params"].get("device_id") == "ext-pc-A"
    # 분담 필터 자체는 유지 — 분담 매칭 잡도 정상 dequeue 되어야 함
    assert "UPPER(site) IN" in sql


def test_no_owner_bypass_when_device_id_absent(monkeypatch):
    """device_id 없는 익명 폴링이면 owner 우회 절 미부착 (분담 그대로 적용)."""
    cap = _run_get_next_job(monkeypatch, device_id="", allowed_sites=["SSG"])
    sql = _norm(cap["sql"])

    assert "owner_device_id = :device_id" not in sql, (
        f"device_id 없는데 owner 우회 절이 붙음:\n{sql}"
    )


def test_allowed_sites_none_skips_site_filter(monkeypatch):
    """분담 None(전체 처리 PC) → site 필터 자체 미적용 — 기존 동작 유지."""
    cap = _run_get_next_job(monkeypatch, device_id="ext-pc-A", allowed_sites=None)
    sql = _norm(cap["sql"])

    assert "UPPER(site) IN" not in sql, f"분담 None 인데 site 필터가 붙음:\n{sql}"


# ──────────────────────────────────────────────────────────────────────────
# 적립(reward) dequeue 측 데몬전용 가드 — 2026-06-22 후속 수정
#
# PR #463(발행 측 DAEMON_ONLY_JOB_SITES["reward"]=set())만으로는 부족했다:
# get_next_job 의 DAEMON_ONLY_SITES 가드(dequeue 측 2번째 장벽)에 reward 가 허용
# job_type 으로 빠져 있어, ABC/SSG/그랜드/롯데ON 적립을 owner 로 트리거 PC 에 박아도
# 비데몬(확장앱) device 가 dequeue 못 했다 → SW 에 [적립금] 잡 수신조차 안 떴음.
# ──────────────────────────────────────────────────────────────────────────


def test_reward_dequeuable_by_extension_for_daemon_only_site(monkeypatch):
    """비데몬(확장앱) device 의 데몬전용 가드 허용 job_type 목록에 reward 포함."""
    cap = _run_get_next_job(
        monkeypatch, device_id="ext-pc-A", allowed_sites=["MUSINSA"]
    )
    sql = _norm(cap["sql"])

    assert "'cancel_order', 'tracking', 'store_metrics', 'purchase', 'reward'" in sql, (
        f"dequeue 가드 허용목록에 reward 없음 — ABC/SSG 적립 확장앱 dequeue 차단됨:\n{sql}"
    )


def test_daemon_device_excluded_from_reward(monkeypatch):
    """데몬 device 는 reward 잡 제외 — 적립은 content-reward-*.js 전담(데몬 핸들러 없음)."""
    cap = _run_get_next_job(monkeypatch, device_id="samba-daemon-x", allowed_sites=None)
    sql = _norm(cap["sql"])

    assert (
        "job_type NOT IN ('tracking', 'store_metrics', 'purchase', 'reward')" in sql
    ), f"데몬 분기에서 reward 차단이 빠짐:\n{sql}"
