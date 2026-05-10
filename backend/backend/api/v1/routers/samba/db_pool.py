"""DB 커넥션 풀 진단 엔드포인트.

- GET /admin/db/pool          : 풀 상태 + 장기 점유 세션 + pg_stat_activity 상위
- POST /admin/db/pool/kill_idle: idle in transaction 세션 강제 종료(긴급용)
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/db", tags=["samba-db-pool"])


@router.get("/pool")
async def get_pool_status() -> dict[str, Any]:
    """현재 write/read 풀 상태와 장기 점유 세션, DB 측 PID 활동 반환."""
    from backend.db.orm import get_write_engine
    from backend.db.pool_monitor import get_active_db_activity, pool_snapshot

    snapshot = pool_snapshot()

    pg_activity: list[dict[str, Any]] = []
    try:
        write_eng = get_write_engine()
        pg_activity = await get_active_db_activity(write_eng, limit=20)
    except Exception as e:
        logger.warning("[pool_status] pg_stat_activity 조회 실패: %s", e)

    # idle in transaction / active 카운트 요약
    state_counts: dict[str, int] = {}
    for row in pg_activity:
        st = (row.get("state") or "unknown") or "unknown"
        state_counts[st] = state_counts.get(st, 0) + 1

    return {
        "snapshot": snapshot,
        "pg_state_counts": state_counts,
        "pg_top_activity": pg_activity,
    }


@router.post("/pool/kill_idle")
async def kill_idle_in_transaction(min_age_sec: int = 60) -> dict[str, Any]:
    """idle in transaction 상태가 min_age_sec 이상인 세션을 강제 종료.

    - 기본 60초 미만은 정상 트랜잭션일 수 있으므로 보호
    - 풀 고갈 긴급 복구용. 일상적으로 쓰지 말 것.
    """
    if min_age_sec < 30:
        raise HTTPException(status_code=400, detail="min_age_sec >= 30 required")

    from sqlalchemy import text

    from backend.db.orm import get_write_engine

    eng = get_write_engine()
    sql = text(
        """
        SELECT pg_terminate_backend(pid) AS terminated, pid
          FROM pg_stat_activity
         WHERE datname = current_database()
           AND state = 'idle in transaction'
           AND state_change < now() - (:age || ' seconds')::interval
           AND pid <> pg_backend_pid()
        """
    )
    async with eng.connect() as conn:
        result = await conn.execute(sql, {"age": min_age_sec})
        rows = result.mappings().all()
    killed = [int(r["pid"]) for r in rows if r.get("terminated")]
    logger.warning(
        "[pool_kill_idle] terminated=%d min_age=%ds pids=%s",
        len(killed),
        min_age_sec,
        killed,
    )
    return {"terminated_count": len(killed), "pids": killed}
