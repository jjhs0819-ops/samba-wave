"""SambaWave Return repository."""

import re
from datetime import datetime
from typing import List, Optional

from sqlmodel import select

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.returns.model import SambaReturn
from backend.utils.logger import logger

# 다중 주문번호 조회 상한 (요청 #9) — 초과분은 경고 로그 후 앞 200개만 사용
MAX_ORDER_NUMBER_TOKENS = 200


class SambaReturnRepository(BaseRepository[SambaReturn]):
    def __init__(self, session):
        super().__init__(session, SambaReturn)

    async def list_by_order(self, order_id: str) -> List[SambaReturn]:
        return await self.filter_by_async(
            order_id=order_id, order_by="created_at", order_by_desc=True
        )

    async def list_by_status(self, status: str) -> List[SambaReturn]:
        return await self.filter_by_async(
            status=status, order_by="created_at", order_by_desc=True
        )

    async def list_by_type(self, type: str) -> List[SambaReturn]:
        return await self.filter_by_async(
            type=type, order_by="created_at", order_by_desc=True
        )

    async def list_filtered(
        self,
        skip: int = 0,
        limit: int = 500,
        order_id: Optional[str] = None,
        order_number: Optional[str] = None,
        status: Optional[str] = None,
        type: Optional[str] = None,
        start_dt: Optional[datetime] = None,
        end_dt: Optional[datetime] = None,
        tenant_id: Optional[str] = None,
    ) -> List[SambaReturn]:
        """필터 + 날짜 범위 목록 조회."""
        from sqlalchemy import or_

        stmt = select(SambaReturn)
        # 테넌트 격리 — NULL은 레거시 데이터로 허용 (backfill 완료 후 제거)
        if tenant_id:
            stmt = stmt.where(
                or_(SambaReturn.tenant_id == tenant_id, SambaReturn.tenant_id.is_(None))
            )
        if order_id:
            stmt = stmt.where(SambaReturn.order_id == order_id)
        # 특정 주문번호 필터 — 날짜 범위 밖이라도 해당 주문 반품/교환은 잡힘
        # (주문관리에서 /returns?order_number=XXXX 새 탭 진입용)
        # 다중 주문번호 지원 (요청 #9): 값 안에 개행·쉼표·공백으로 여러 건이 올 수 있다.
        # 파라미터 시그니처는 그대로 두고 값만 토큰화해 하위호환 유지.
        if order_number:
            # 토큰화 → 빈 토큰 제거 → 순서 보존 중복 제거
            tokens = list(
                dict.fromkeys(t for t in re.split(r"[\s,]+", order_number) if t)
            )
            if len(tokens) > MAX_ORDER_NUMBER_TOKENS:
                # 상한 초과는 에러로 막지 않고 앞 200개만 사용 (경고 로그만)
                logger.warning(
                    "list_filtered: order_number 토큰 %d개 → 상한 %d개로 절단",
                    len(tokens),
                    MAX_ORDER_NUMBER_TOKENS,
                )
                tokens = tokens[:MAX_ORDER_NUMBER_TOKENS]
            if len(tokens) >= 2:
                stmt = stmt.where(SambaReturn.order_number.in_(tokens))
            elif len(tokens) == 1:
                # 단건은 기존과 동일한 정확일치 — 하위호환 보장
                stmt = stmt.where(SambaReturn.order_number == tokens[0])
            else:
                # 구분자만 들어온 극단 케이스 — 기존 동작(원문 정확일치)으로 폴백
                stmt = stmt.where(SambaReturn.order_number == order_number)
        if status:
            stmt = stmt.where(SambaReturn.status == status)
        if type:
            stmt = stmt.where(SambaReturn.type == type)
        # 날짜 필터를 order_date로 변경 — created_at은 record 생성 시점, order_date는 실제 주문일
        # order_date가 null인 레거시 레코드는 항상 포함
        if start_dt:
            stmt = stmt.where(
                or_(
                    SambaReturn.order_date >= start_dt, SambaReturn.order_date.is_(None)
                )
            )
        if end_dt:
            stmt = stmt.where(
                or_(SambaReturn.order_date <= end_dt, SambaReturn.order_date.is_(None))
            )
        stmt = stmt.order_by(SambaReturn.created_at.desc())
        stmt = stmt.offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
