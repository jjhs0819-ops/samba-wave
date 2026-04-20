"""SMS/카카오 발송 이력 레포지토리."""

from __future__ import annotations

from typing import List, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.samba.message_log.model import MessageLog


class MessageLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, log: MessageLog) -> MessageLog:
        self.session.add(log)
        await self.session.commit()
        await self.session.refresh(log)
        return log

    async def list_by_order(
        self, order_id: str, tenant_id: Optional[str] = None
    ) -> List[MessageLog]:
        stmt = (
            select(MessageLog)
            .where(MessageLog.order_id == order_id)
            .order_by(MessageLog.sent_at.desc())
        )
        if tenant_id is not None:
            stmt = stmt.where(MessageLog.tenant_id == tenant_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_phone(
        self, phone: str, tenant_id: Optional[str] = None
    ) -> List[MessageLog]:
        stmt = (
            select(MessageLog)
            .where(MessageLog.customer_phone == phone)
            .order_by(MessageLog.sent_at.desc())
        )
        if tenant_id is not None:
            stmt = stmt.where(MessageLog.tenant_id == tenant_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_sent_flags(
        self, order_ids: List[str], tenant_id: Optional[str] = None
    ) -> dict[str, dict[str, bool]]:
        """order_id 목록에 대해 sms/kakao 발송 여부 반환."""
        if not order_ids:
            return {}
        stmt = select(MessageLog.order_id, MessageLog.message_type).where(
            MessageLog.order_id.in_(order_ids),
            MessageLog.success == True,  # noqa: E712
        )
        if tenant_id is not None:
            stmt = stmt.where(MessageLog.tenant_id == tenant_id)
        result = await self.session.execute(stmt)
        rows = result.all()

        flags: dict[str, dict[str, bool]] = {}
        for oid, mtype in rows:
            if oid not in flags:
                flags[oid] = {"sms": False, "kakao": False}
            if mtype == "sms":
                flags[oid]["sms"] = True
            elif mtype == "kakao":
                flags[oid]["kakao"] = True
        return flags
