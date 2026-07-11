"""계정 차선 우선순위(부분 양보) 단위 테스트.

배경: 대량 신규전송(high)과 오토튠 가격/재고 update(low)가 같은 계정 세마포어(동시 1건)를
공유해, 오토튠 부하가 크면 신규등록이 오토튠 뒤에 밀려 건당 수십초~수분 지연되던 문제.
해결: 신규등록(high)이 대기 중이면 오토튠(low)이 양보하되 floor/시간 상한으로 굶지 않게 함.

여기서는 _acquire_account_lane 을 lane 상태(hp_waiting/hp_served)를 직접 제어하며
결정론적으로 검증한다. 기본 OFF(플래그) → 동작 불변도 확인.
"""

import asyncio
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.shipment import service as svc


@pytest.fixture(autouse=True)
def _reset_lanes(monkeypatch):
    """각 테스트 전 차선 상태 초기화 + 기본 파라미터 세팅."""
    svc._account_lanes.clear()
    monkeypatch.setattr(svc, "_LANE_PRIORITY_SLICE", 0.01, raising=False)
    yield
    svc._account_lanes.clear()


async def test_disabled_low_does_not_yield(monkeypatch):
    """플래그 OFF면 high 가 대기 중이어도 low 는 양보하지 않고 즉시 획득."""
    monkeypatch.setattr(svc, "_LANE_PRIORITY_ENABLED", False, raising=False)
    lane = svc._get_account_lane("acc")
    lane.hp_waiting = 1  # high 대기 중 상황을 흉내

    t0 = asyncio.get_event_loop().time()
    got = await svc._acquire_account_lane("acc", "low", timeout=5)
    elapsed = asyncio.get_event_loop().time() - t0

    assert got is lane
    assert elapsed < 0.05  # 양보 없이 즉시
    svc._release_account_lane(got)


async def test_enabled_low_yields_until_high_clears(monkeypatch):
    """플래그 ON + high 대기 중이면 low 는 양보하다가, high 가 빠지면 곧 획득."""
    monkeypatch.setattr(svc, "_LANE_PRIORITY_ENABLED", True, raising=False)
    monkeypatch.setattr(svc, "_LANE_PRIORITY_FLOOR", 9999, raising=False)
    monkeypatch.setattr(svc, "_LANE_PRIORITY_MAX_YIELD_SEC", 5.0, raising=False)
    lane = svc._get_account_lane("acc")
    lane.hp_waiting = 1  # high 가 계속 대기 중

    async def _clear_after():
        await asyncio.sleep(0.1)
        lane.hp_waiting = 0  # high 가 처리 완료돼 대기 사라짐

    asyncio.create_task(_clear_after())
    t0 = asyncio.get_event_loop().time()
    got = await svc._acquire_account_lane("acc", "low", timeout=5)
    elapsed = asyncio.get_event_loop().time() - t0

    assert got is lane
    assert 0.08 < elapsed < 1.0  # high 빠질 때까지 양보 후 획득
    svc._release_account_lane(got)


async def test_low_forced_through_after_floor(monkeypatch):
    """high 가 계속 대기해도 floor 만큼 high 가 지나가면 low 강제 통과(굶주림 방지)."""
    monkeypatch.setattr(svc, "_LANE_PRIORITY_ENABLED", True, raising=False)
    monkeypatch.setattr(svc, "_LANE_PRIORITY_FLOOR", 3, raising=False)
    monkeypatch.setattr(svc, "_LANE_PRIORITY_MAX_YIELD_SEC", 10.0, raising=False)
    lane = svc._get_account_lane("acc")
    lane.hp_waiting = 1  # high 상시 대기

    async def _serve_highs():
        # high 가 하나씩 처리되는 상황(hp_served 증가)을 흉내
        for _ in range(10):
            await asyncio.sleep(0.03)
            lane.hp_served += 1

    asyncio.create_task(_serve_highs())
    t0 = asyncio.get_event_loop().time()
    got = await svc._acquire_account_lane("acc", "low", timeout=5)
    elapsed = asyncio.get_event_loop().time() - t0

    assert got is lane
    # floor=3 → high 3건 지나가면(≈0.09s) 통과, max_yield(10s)보다 훨씬 이르게
    assert 0.05 < elapsed < 1.0
    svc._release_account_lane(got)


async def test_low_forced_through_by_time_cap(monkeypatch):
    """floor 미달이라도 시간 상한(max_yield) 초과 시 low 강제 통과."""
    monkeypatch.setattr(svc, "_LANE_PRIORITY_ENABLED", True, raising=False)
    monkeypatch.setattr(svc, "_LANE_PRIORITY_FLOOR", 9999, raising=False)
    monkeypatch.setattr(svc, "_LANE_PRIORITY_MAX_YIELD_SEC", 0.15, raising=False)
    lane = svc._get_account_lane("acc")
    lane.hp_waiting = 1  # high 상시 대기(사라지지 않음), hp_served 도 안 늘음

    t0 = asyncio.get_event_loop().time()
    got = await svc._acquire_account_lane("acc", "low", timeout=5)
    elapsed = asyncio.get_event_loop().time() - t0

    assert got is lane
    assert 0.13 < elapsed < 1.0  # 시간 상한 후 통과
    svc._release_account_lane(got)


async def test_high_never_yields(monkeypatch):
    """high 는 다른 high 가 대기 중이어도 양보 로직을 타지 않고 즉시 획득(락 비어있으면)."""
    monkeypatch.setattr(svc, "_LANE_PRIORITY_ENABLED", True, raising=False)
    lane = svc._get_account_lane("acc")
    lane.hp_waiting = 5  # 다른 high 다수 대기 상황

    t0 = asyncio.get_event_loop().time()
    got = await svc._acquire_account_lane("acc", "high", timeout=5)
    elapsed = asyncio.get_event_loop().time() - t0

    assert got is lane
    assert elapsed < 0.05
    assert lane.hp_served == 1  # high 획득 카운트 증가
    svc._release_account_lane(got)


async def test_mutual_exclusion_still_holds(monkeypatch):
    """차선은 여전히 동시 1건만 허용(상호배제)."""
    monkeypatch.setattr(svc, "_LANE_PRIORITY_ENABLED", True, raising=False)
    order: list[str] = []

    async def worker(name: str, prio: str):
        lane = await svc._acquire_account_lane("acc", prio, timeout=5)
        order.append(f"{name}:in")
        await asyncio.sleep(0.05)
        order.append(f"{name}:out")
        svc._release_account_lane(lane)

    await asyncio.gather(worker("a", "high"), worker("b", "high"))
    # 겹침 없이 in/out 이 쌍으로 직렬 — 어느 하나가 완전히 끝난 뒤 다음이 시작
    assert order in (
        ["a:in", "a:out", "b:in", "b:out"],
        ["b:in", "b:out", "a:in", "a:out"],
    )


async def test_release_unlocked_is_safe():
    """미획득 lane release 는 예외 없이 무시."""
    lane = svc._get_account_lane("acc")
    svc._release_account_lane(lane)  # 락 안 잡힌 상태 — 크래시 없어야
