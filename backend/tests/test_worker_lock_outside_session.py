"""전송 계정 락을 DB 세션 밖에서 잡는지 검증.

배경(2026-08-19 운영 조사): _execute_job 이 write 세션을 먼저 열고
`SELECT samba_jobs`(session.get)로 트랜잭션을 시작한 뒤, 그 안에서 계정 락을
기다리고 마켓 전송(1~10초)까지 수행했다. 그 결과 커넥션이 'idle in transaction'
상태로 묶여 운영 DB 에서 58~77개가 수십 초~분 단위로 고착됐고, 열린 스냅샷이
죽은 튜플 회수를 막았다.

락 대기는 DB 가 전혀 필요 없으므로 세션보다 먼저 잡아야 한다. 이 테스트는
'락을 못 잡는 동안에는 DB 세션을 열지 않는다'는 성질을 직접 확인한다.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.job import worker as worker_mod


class _FakeJob:
    id = "job_test_1"
    job_type = "autotune_transmit"
    payload = {"target_account_ids": ["acc_A"]}


@pytest.fixture
def _worker(monkeypatch):
    w = worker_mod.JobWorker()
    # 전송 본체는 실행하지 않는다 — 여기서 보는 건 락/세션 순서뿐.
    async def _noop_transmit(*_a, **_k):
        return None
    monkeypatch.setattr(w, "_run_transmit", _noop_transmit, raising=False)
    return w


def _install_session_spy(monkeypatch, opened: list):
    """get_write_session 호출 시점을 기록하는 스파이 설치."""

    class _FakeSession:
        async def get(self, *_a, **_k):
            return _FakeJob()

        async def commit(self):
            return None

    @asynccontextmanager
    async def _fake_get_write_session():
        opened.append(True)
        yield _FakeSession()

    import backend.db.orm as orm

    monkeypatch.setattr(orm, "get_write_session", _fake_get_write_session)
    monkeypatch.setattr(
        worker_mod, "SambaJobRepository", lambda _s: object(), raising=False
    )


async def test_락을_못_잡으면_DB세션을_열지_않는다(_worker, monkeypatch):
    opened: list = []
    _install_session_spy(monkeypatch, opened)

    # 다른 잡이 같은 계정 락을 이미 쥐고 있는 상황을 만든다.
    lock = _worker._get_transmit_account_lock("acc_A")
    await lock.acquire()

    task = asyncio.create_task(_worker._execute_job(_FakeJob()))
    await asyncio.sleep(0.05)

    assert opened == [], (
        "락 대기 중에 write 세션을 열면 안 된다 — 그 커넥션이 "
        "idle in transaction 으로 묶인다"
    )

    # 락을 풀면 그제서야 세션을 연다.
    lock.release()
    await asyncio.wait_for(task, timeout=2)
    assert opened, "락 획득 후에는 세션을 열어 잡을 처리해야 한다"


async def test_잡이_끝나면_계정락이_반드시_풀린다(_worker, monkeypatch):
    opened: list = []
    _install_session_spy(monkeypatch, opened)

    await asyncio.wait_for(_worker._execute_job(_FakeJob()), timeout=2)

    lock = _worker._get_transmit_account_lock("acc_A")
    assert not lock.locked(), "잡 종료 후 락이 남으면 같은 계정 전송이 영구 정지한다"


async def test_전송_중_예외가_나도_계정락이_풀린다(_worker, monkeypatch):
    opened: list = []
    _install_session_spy(monkeypatch, opened)

    async def _boom(*_a, **_k):
        raise RuntimeError("전송 실패")

    monkeypatch.setattr(_worker, "_run_transmit", _boom, raising=False)

    await asyncio.wait_for(_worker._execute_job(_FakeJob()), timeout=2)

    lock = _worker._get_transmit_account_lock("acc_A")
    assert not lock.locked(), "예외 경로에서도 락은 반드시 해제돼야 한다"
