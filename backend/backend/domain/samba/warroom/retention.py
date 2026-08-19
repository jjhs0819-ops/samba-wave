"""samba_monitor_event 보존정책.

## 왜 필요한가

모니터 이벤트에는 정리 로직이 아예 없었다. 2026-08-19 운영 DB 실측으로
**12,801,565행 / 17GB**(heap 7.7GB + 인덱스 9.3GB)까지 자랐고, 그중 97.6%가
오토튠이 매 가격변동마다 남기는 `price_changed` 였다. 한 달치가 저 정도라
방치하면 연 200GB 로 늘어난다. 게다가 이 테이블은 autovacuum 이 한 번도
완주하지 못해(analyze/vacuum 이력 0) 플래너 통계도 42행으로 잘못 잡혀 있었다.

## 보존 기간 근거

실제 조회 시간창을 코드에서 확인해 정했다.
- 워룸 대시보드(`warroom/repository.py`)  : 최근 **1일**
- 유령 배너(`shipments/ghost-summary`)     : `hours` 상한 720 = **30일**

따라서 고빈도 텔레메트리는 14일, 그 외(유령감지 등)는 90일이면 화면 기능에
영향이 없고 충분한 여유가 있다. 두 값 모두 env 로 조정 가능하다.

## 삭제 방식

한 번에 1,000만 건을 지우면 거대 트랜잭션 + 락 + WAL 폭증으로 운영이 멈춘다.
그래서 **매 실행마다 상한(batch)까지만** 지우고 빠져나온다. 밀린 물량은 여러
사이클에 걸쳐 천천히 소진된다(자기제한적). 지운 공간은 즉시 반환되지 않고
재사용되므로, 파일 크기 축소가 필요하면 별도로 VACUUM FULL/pg_repack 을 한다.
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import bindparam, text

# 오토튠이 초당 수 건씩 남기는 고빈도 텔레메트리 — 짧게 보존한다.
# (운영 실측 분포: price_changed 12.49M / scheduler_tick 69.8K / scheduler_cycle 752)
HIGH_VOLUME_EVENT_TYPES: tuple[str, ...] = (
    "price_changed",
    "scheduler_tick",
    "scheduler_cycle",
)


def high_volume_retention_days() -> int:
    """고빈도 텔레메트리 보존일 (기본 14일 — 워룸 조회창 1일의 14배 여유)."""
    return max(1, int(os.environ.get("MONITOR_EVENT_RETENTION_DAYS", "14")))


def default_retention_days() -> int:
    """그 외 이벤트 보존일 (기본 90일 — 유령배너 조회창 30일의 3배 여유)."""
    return max(
        1, int(os.environ.get("MONITOR_EVENT_RETENTION_DAYS_DEFAULT", "90"))
    )


def purge_batch_limit() -> int:
    """한 사이클에서 지울 최대 행수 (기본 20,000)."""
    return max(1, int(os.environ.get("MONITOR_EVENT_PURGE_BATCH", "20000")))


# ctid 서브쿼리로 배치를 끊는다 — LIMIT 을 DELETE 에 직접 못 거는 Postgres 에서
# 표준적으로 쓰는 방식이다.
#
# ORDER BY created_at 을 일부러 붙이지 않는다. 붙이면 정렬을 인덱스로 만족시키려고
# created_at 인덱스 스캔으로 바뀌는데, 밀린 물량이 많은 지금 구간에서는 heap 을
# 무작위로 훑어 훨씬 느리다. 운영 DB 실측(2026-08-19, 만료 765만 건 상태):
#   ORDER BY 없음 : 버퍼 1,311개    /   36.9ms
#   ORDER BY 있음 : 버퍼 1,257,204개 / 1,355.9ms  ← 37배 악화
# 백로그를 다 소진한 뒤(만료행이 몇천 건뿐일 때)에도 걱정할 필요 없다. 그때는
# 플래너가 알아서 인덱스 스캔을 고른다 — 같은 날 40일 조건으로 확인했고 0.17ms.
# 즉 두 구간 모두 ORDER BY 없는 쪽이 낫다. '정렬이 빠지면 풀스캔이 된다'는 직관은
# 이 테이블에서는 사실이 아니므로, 성능 목적으로 ORDER BY 를 다시 넣지 말 것.
#
# IN 은 expanding 바인딩을 쓴다 — ANY(:types) 는 리스트 파라미터의 배열 타입 추론이
# 드라이버(asyncpg/psycopg)마다 달라 깨질 수 있다. expanding 은 SQLAlchemy 가
# IN (:t_1, :t_2, ...) 로 펼쳐줘서 드라이버와 무관하게 동작한다.
_PURGE_HIGH_VOLUME_SQL = text(
    """
    DELETE FROM samba_monitor_event
     WHERE ctid IN (
           SELECT ctid FROM samba_monitor_event
            WHERE event_type IN :types
              AND created_at < now() - make_interval(days => :days)
            LIMIT :batch
     )
    """
).bindparams(bindparam("types", expanding=True))

# event_type IS NULL 도 삭제 대상에 포함한다 — NOT IN 만 쓰면 NULL 비교가 NULL 이라
# 해당 행이 영원히 안 지워지고 남는다.
_PURGE_DEFAULT_SQL = text(
    """
    DELETE FROM samba_monitor_event
     WHERE ctid IN (
           SELECT ctid FROM samba_monitor_event
            WHERE (event_type IS NULL OR event_type NOT IN :types)
              AND created_at < now() - make_interval(days => :days)
            LIMIT :batch
     )
    """
).bindparams(bindparam("types", expanding=True))


async def purge_expired_monitor_events(session: Any) -> dict[str, int]:
    """보존기간이 지난 모니터 이벤트를 배치 상한까지 삭제하고 건수를 돌려준다.

    고빈도분을 먼저 지우고, 남은 배치 여유가 있을 때만 그 외를 지운다 —
    용량을 잡아먹는 쪽이 고빈도분이라 우선순위를 준다.
    """
    batch = purge_batch_limit()

    high_result = await session.execute(
        _PURGE_HIGH_VOLUME_SQL,
        {
            "types": list(HIGH_VOLUME_EVENT_TYPES),
            "days": high_volume_retention_days(),
            "batch": batch,
        },
    )
    high_deleted = high_result.rowcount or 0

    remaining = batch - high_deleted
    other_deleted = 0
    if remaining > 0:
        other_result = await session.execute(
            _PURGE_DEFAULT_SQL,
            {
                "types": list(HIGH_VOLUME_EVENT_TYPES),
                "days": default_retention_days(),
                "batch": remaining,
            },
        )
        other_deleted = other_result.rowcount or 0

    await session.commit()
    return {
        "high_volume": high_deleted,
        "other": other_deleted,
        "total": high_deleted + other_deleted,
    }
