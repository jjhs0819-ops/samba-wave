"""samba_monitor_event 보존정책 테스트.

운영 실측(2026-08-19): 12,801,565행 / 17GB, 97.6%가 price_changed, 정리 로직 부재.
한 번에 다 지우면 거대 트랜잭션으로 운영이 멈추므로 배치 상한이 핵심이다.
"""

import os

import pytest

from backend.domain.samba.warroom import retention


class _FakeResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _FakeSession:
    """execute 호출 인자를 기록하는 최소 세션 더블."""

    def __init__(self, rowcounts: list[int]) -> None:
        self._rowcounts = list(rowcounts)
        self.calls: list[dict] = []
        self.committed = False

    async def execute(self, _stmt, params):
        self.calls.append(params)
        return _FakeResult(self._rowcounts.pop(0) if self._rowcounts else 0)

    async def commit(self):
        self.committed = True


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in (
        "MONITOR_EVENT_RETENTION_DAYS",
        "MONITOR_EVENT_RETENTION_DAYS_DEFAULT",
        "MONITOR_EVENT_PURGE_BATCH",
    ):
        monkeypatch.delenv(key, raising=False)


async def test_고빈도_이벤트를_먼저_지우고_건수를_돌려준다():
    session = _FakeSession([1200, 30])

    result = await retention.purge_expired_monitor_events(session)

    assert result == {"high_volume": 1200, "other": 30, "total": 1230}
    assert session.committed is True
    assert "price_changed" in session.calls[0]["types"]


async def test_배치_상한을_절대_넘기지_않는다():
    """고빈도분이 상한을 다 먹으면 그 외 삭제는 아예 시도하지 않는다."""
    batch = retention.purge_batch_limit()
    session = _FakeSession([batch, 999])

    result = await retention.purge_expired_monitor_events(session)

    assert result["other"] == 0, "상한 소진 후에는 추가 삭제를 하면 안 된다"
    assert result["total"] == batch
    assert len(session.calls) == 1, "두 번째 DELETE 를 실행하면 안 된다"


async def test_남은_여유만큼만_그_외를_지운다():
    batch = retention.purge_batch_limit()
    session = _FakeSession([batch - 5, 5])

    await retention.purge_expired_monitor_events(session)

    assert session.calls[1]["batch"] == 5


async def test_보존일_기본값은_조회창보다_넉넉하다():
    # 워룸 대시보드 조회창 1일, 유령배너 상한 30일 — 그보다 짧으면 화면이 깨진다.
    assert retention.high_volume_retention_days() >= 1
    assert retention.default_retention_days() >= 30


async def test_env_로_보존일과_배치를_조정할_수_있다(monkeypatch):
    monkeypatch.setenv("MONITOR_EVENT_RETENTION_DAYS", "3")
    monkeypatch.setenv("MONITOR_EVENT_RETENTION_DAYS_DEFAULT", "45")
    monkeypatch.setenv("MONITOR_EVENT_PURGE_BATCH", "500")

    session = _FakeSession([10, 10])
    await retention.purge_expired_monitor_events(session)

    assert session.calls[0]["days"] == 3
    assert session.calls[0]["batch"] == 500
    assert session.calls[1]["days"] == 45


async def test_0이나_음수_설정은_최소값으로_방어된다(monkeypatch):
    monkeypatch.setenv("MONITOR_EVENT_RETENTION_DAYS", "0")
    monkeypatch.setenv("MONITOR_EVENT_PURGE_BATCH", "-100")

    # 보존일 0 이면 방금 쌓인 이벤트까지 지워 워룸이 빈다. 배치 음수는 무한루프 위험.
    assert retention.high_volume_retention_days() == 1
    assert retention.purge_batch_limit() == 1


async def test_지울_게_없으면_0을_돌려준다():
    session = _FakeSession([0, 0])

    result = await retention.purge_expired_monitor_events(session)

    assert result["total"] == 0
