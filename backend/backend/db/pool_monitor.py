"""DB 커넥션 풀 모니터링 — 사용률·세션 보유시간 가시화.

목적:
- 풀 사용률 30초마다 INFO 로깅, 80% 초과 시 WARN
- 세션 checkout-checkin 시간 측정, SLOW_SESSION_THRESHOLD 초과 시 WARN(스택 포함)
- /admin/db/pool 엔드포인트에서 즉시 상태 + 장기 점유 PID 조회 가능
"""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

# 세션이 5초 이상 점유되면 경고 (외부 API 호출이 세션 안에서 일어나는 안티패턴 탐지)
SLOW_SESSION_THRESHOLD_SEC = 5.0
# 풀 사용률 경고 임계
POOL_USAGE_WARN_RATIO = 0.8
# 풀 상태 로깅 주기
POOL_LOG_INTERVAL_SEC = 30.0

# (engine_name, connection_id) → (checkout_ts, traceback_summary)
_checkout_log: dict[tuple[str, int], tuple[float, str]] = {}

# 모니터 등록된 엔진 추적 — 중복 등록 방지
_attached_engines: set[int] = set()

# (engine_name, AsyncEngine) — pool_status_logger가 사용
_monitored_engines: list[tuple[str, AsyncEngine]] = []


def _short_stack(skip: int = 2, limit: int = 4) -> str:
    """현재 호출 스택을 요약 — sqlalchemy/asyncio 내부 프레임 스킵 후 backend 코드 우선.

    SQLAlchemy pool checkout 이벤트 안에서 호출되므로 단순 tail 추출 시 sqlalchemy
    내부만 잡힘. backend/ 경로 프레임을 우선 추출하고, 없을 때만 호출 직전 프레임 노출.
    """
    frames = traceback.extract_stack()[:-skip]
    backend_frames: list[traceback.FrameSummary] = []
    for f in frames:
        fn = (f.filename or "").replace("\\", "/")
        # 외부 라이브러리 스킵
        if "/site-packages/" in fn or "/.venv/" in fn:
            continue
        # 너무 일반적인 framework 진입점 스킵
        if fn.endswith("/asyncio/events.py") or fn.endswith("/asyncio/base_events.py"):
            continue
        if "/backend/" in fn or "\\backend\\" in fn or fn.startswith("backend/"):
            backend_frames.append(f)
    picked = backend_frames[-limit:] if backend_frames else frames[-limit:]

    def _fmt(f: traceback.FrameSummary) -> str:
        fn = (f.filename or "").replace("\\", "/")
        # backend/ 이후 경로만 표기
        idx = fn.rfind("/backend/")
        short = fn[idx + 1 :] if idx >= 0 else fn.split("/")[-1]
        return f"{short}:{f.lineno}({f.name})"

    return " | ".join(_fmt(f) for f in picked)


def attach_pool_monitor(async_engine: AsyncEngine, name: str) -> None:
    """엔진에 checkout/checkin 이벤트 훅 등록.

    AsyncEngine.sync_engine에 이벤트를 붙여야 동작 (SQLAlchemy 이벤트는 동기 엔진 기준).
    """
    sync_engine: Engine = async_engine.sync_engine
    eid = id(sync_engine)
    if eid in _attached_engines:
        return
    _attached_engines.add(eid)
    _monitored_engines.append((name, async_engine))

    @event.listens_for(sync_engine, "checkout")
    def _on_checkout(dbapi_conn, conn_record, conn_proxy):
        try:
            stack = _short_stack(skip=3, limit=3)
        except Exception:
            stack = "?"
        _checkout_log[(name, id(conn_record))] = (time.monotonic(), stack)

    @event.listens_for(sync_engine, "checkin")
    def _on_checkin(dbapi_conn, conn_record):
        key = (name, id(conn_record))
        info = _checkout_log.pop(key, None)
        if not info:
            return
        held = time.monotonic() - info[0]
        if held >= SLOW_SESSION_THRESHOLD_SEC:
            logger.warning(
                "[DB풀] 장시간 세션 보유 engine=%s held=%.2fs stack=%s",
                name,
                held,
                info[1],
            )

    logger.info("[DB풀] 모니터 부착 완료 engine=%s", name)


def pool_snapshot() -> dict[str, Any]:
    """현재 풀 상태 + 장기 점유 세션 목록."""
    out: dict[str, Any] = {"engines": {}, "long_held_sessions": []}
    now = time.monotonic()
    for name, eng in _monitored_engines:
        try:
            pool = eng.sync_engine.pool
            size = pool.size()
            checked_out = pool.checkedout()
            overflow = pool.overflow()
            total_capacity = size + getattr(pool, "_max_overflow", 0)
            usage_ratio = (checked_out / total_capacity) if total_capacity else 0.0
            out["engines"][name] = {
                "size": size,
                "checked_out": checked_out,
                "overflow": overflow,
                "max_overflow": getattr(pool, "_max_overflow", None),
                "total_capacity": total_capacity,
                "usage_ratio": round(usage_ratio, 3),
            }
        except Exception as e:
            out["engines"][name] = {"error": str(e)}

    # 장기 점유 세션
    for (eng_name, _cid), (ts, stack) in list(_checkout_log.items()):
        held = now - ts
        if held >= SLOW_SESSION_THRESHOLD_SEC:
            out["long_held_sessions"].append(
                {"engine": eng_name, "held_sec": round(held, 2), "stack": stack}
            )
    out["long_held_sessions"].sort(key=lambda x: -x["held_sec"])
    out["long_held_sessions"] = out["long_held_sessions"][:20]
    return out


async def get_active_db_activity(
    async_engine: AsyncEngine, limit: int = 10
) -> list[dict[str, Any]]:
    """pg_stat_activity에서 장기 점유/idle in transaction PID 조회."""
    from sqlalchemy import text

    sql = text(
        """
        SELECT pid,
               state,
               wait_event_type,
               wait_event,
               EXTRACT(EPOCH FROM (now() - state_change))::int AS state_age_sec,
               EXTRACT(EPOCH FROM (now() - query_start))::int AS query_age_sec,
               LEFT(query, 200) AS query_head
          FROM pg_stat_activity
         WHERE datname = current_database()
           AND pid <> pg_backend_pid()
         ORDER BY state_change ASC
         LIMIT :lim
        """
    )
    async with async_engine.connect() as conn:
        result = await conn.execute(sql, {"lim": limit})
        rows = result.mappings().all()
    return [dict(r) for r in rows]


async def pool_status_logger_loop() -> None:
    """주기적으로 풀 상태 로깅. 80% 초과 시 WARN."""
    logger.info("[DB풀] 모니터 로거 시작 interval=%.0fs", POOL_LOG_INTERVAL_SEC)
    while True:
        try:
            await asyncio.sleep(POOL_LOG_INTERVAL_SEC)
            snap = pool_snapshot()
            for name, info in snap["engines"].items():
                if "error" in info:
                    logger.warning("[DB풀] %s 상태 조회 실패: %s", name, info["error"])
                    continue
                ratio = info["usage_ratio"]
                msg = (
                    f"[DB풀] {name} "
                    f"checked_out={info['checked_out']}/{info['total_capacity']} "
                    f"(size={info['size']} overflow={info['overflow']}) "
                    f"usage={ratio * 100:.0f}%"
                )
                if ratio >= POOL_USAGE_WARN_RATIO:
                    logger.warning(msg)
                else:
                    logger.info(msg)
            long_sessions = snap.get("long_held_sessions") or []
            if long_sessions:
                logger.warning(
                    "[DB풀] 장기 점유 세션 %d건 (top: %s)",
                    len(long_sessions),
                    long_sessions[0],
                )
        except asyncio.CancelledError:
            logger.info("[DB풀] 모니터 로거 종료")
            raise
        except Exception as e:
            logger.exception("[DB풀] 모니터 로거 예외: %s", e)
