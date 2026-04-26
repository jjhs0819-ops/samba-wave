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

    await repo.complete_job(job.id, result={"synced": synced, "linked": linked})
