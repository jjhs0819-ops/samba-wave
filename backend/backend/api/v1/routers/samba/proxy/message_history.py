"""SMS/카카오 발송 이력 조회 엔드포인트."""

from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency
from backend.domain.samba.message_log.repository import MessageLogRepository
from backend.domain.samba.tenant.middleware import get_optional_tenant_id

router = APIRouter(tags=["samba-proxy"])


@router.get("/messages/by-order/{order_id}")
async def get_messages_by_order(
    order_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
) -> List[dict[str, Any]]:
    """특정 주문의 발송 이력 조회 (최신순)."""
    repo = MessageLogRepository(session)
    logs = await repo.list_by_order(order_id, tenant_id)
    return [
        {
            "id": log.id,
            "message_type": log.message_type,
            "rendered_message": log.rendered_message,
            "receiver": log.receiver,
            "sent_at": log.sent_at.isoformat() if log.sent_at else None,
            "success": log.success,
            "result_message": log.result_message,
        }
        for log in logs
    ]


@router.get("/messages/sent-flags")
async def get_sent_flags(
    order_ids: str = Query(..., description="콤마로 구분된 order_id 목록"),
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
) -> dict[str, Any]:
    """주문 목록에 대한 SMS/카카오 발송 여부 일괄 조회."""
    ids = [i.strip() for i in order_ids.split(",") if i.strip()]
    repo = MessageLogRepository(session)
    flags = await repo.get_sent_flags(ids, tenant_id)
    return flags
