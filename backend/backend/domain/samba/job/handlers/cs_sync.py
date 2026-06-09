"""cs_sync 잡 핸들러 — CS 문의 전체 마켓 동기화."""

from __future__ import annotations

import logging
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.samba.job.model import SambaJob
from backend.domain.samba.job.repository import SambaJobRepository
from backend.domain.samba.job.worker import _add_job_log

logger = logging.getLogger(__name__)


async def run(
    job: SambaJob,
    repo: SambaJobRepository,
    session: AsyncSession,
    worker: Any | None = None,
) -> None:
    """전체 마켓 CS 문의 동기화.

    payload: (없음 — 전체 마켓 동기화만 지원)
    """
    _add_job_log(job.id, "CS 문의 동기화 시작")

    # 테넌트 격리: 백그라운드 잡은 ContextVar가 비어 있어 ORM 자동 tenant 필터가
    # 패스된다. job.tenant_id를 ContextVar에 세팅하면
    # ① 마켓계정 SELECT가 해당 테넌트로 자동 격리되고
    # ② 새로 수집되는 CS 문의 INSERT에 tenant_id가 자동 스탬프된다.
    from backend.core.tenant_context import current_tenant_id

    token = current_tenant_id.set(job.tenant_id)
    try:
        from backend.api.v1.routers.samba.cs_inquiry import _do_sync_cs_from_markets

        result = await _do_sync_cs_from_markets(session)
        synced = result.get("synced", 0) if isinstance(result, dict) else 0
        linked = result.get("linked", 0) if isinstance(result, dict) else 0
        _add_job_log(
            job.id, f"CS 문의 동기화 완료 — {synced}건 수집, {linked}건 상품연결"
        )
    except Exception as e:
        logger.error(f"[cs_sync] CS 동기화 실패: {e}")
        _add_job_log(job.id, f"CS 동기화 오류: {e}")
        raise
    finally:
        current_tenant_id.reset(token)

    await repo.complete_job(job.id, result={"synced": synced, "linked": linked})
