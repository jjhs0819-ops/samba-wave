"""SambaWave CS 문의 repository."""

from typing import List, Optional

from sqlalchemy import func
from sqlmodel import select

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.cs_inquiry.model import SambaCSInquiry


class SambaCSInquiryRepository(BaseRepository[SambaCSInquiry]):
    def __init__(self, session):
        super().__init__(session, SambaCSInquiry)

    async def list_filtered(
        self,
        skip: int = 0,
        limit: int = 30,
        market: Optional[str] = None,
        inquiry_type: Optional[str] = None,
        reply_status: Optional[str] = None,
        search: Optional[str] = None,
        sort_field: str = "inquiry_date",
        sort_desc: bool = True,
    ) -> List[SambaCSInquiry]:
        """필터 + 정렬 + 페이지네이션 목록 조회."""
        stmt = select(SambaCSInquiry).where(SambaCSInquiry.is_hidden == False)  # noqa: E712

        if market:
            stmt = stmt.where(SambaCSInquiry.market == market)
        if inquiry_type:
            stmt = stmt.where(SambaCSInquiry.inquiry_type == inquiry_type)
        if reply_status:
            stmt = stmt.where(SambaCSInquiry.reply_status == reply_status)
        if search:
            stmt = stmt.where(
                SambaCSInquiry.product_name.ilike(f"%{search}%")  # type: ignore
                | SambaCSInquiry.content.ilike(f"%{search}%")  # type: ignore
                | SambaCSInquiry.market_order_id.ilike(f"%{search}%")  # type: ignore
            )

        # 정렬
        col = getattr(SambaCSInquiry, sort_field, SambaCSInquiry.inquiry_date)
        stmt = stmt.order_by(col.desc() if sort_desc else col.asc())
        stmt = stmt.offset(skip).limit(limit)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_filtered(
        self,
        market: Optional[str] = None,
        inquiry_type: Optional[str] = None,
        reply_status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> int:
        """필터 적용된 총 개수."""
        stmt = (
            select(func.count())
            .select_from(SambaCSInquiry)
            .where(SambaCSInquiry.is_hidden == False)
        )  # noqa: E712

        if market:
            stmt = stmt.where(SambaCSInquiry.market == market)
        if inquiry_type:
            stmt = stmt.where(SambaCSInquiry.inquiry_type == inquiry_type)
        if reply_status:
            stmt = stmt.where(SambaCSInquiry.reply_status == reply_status)
        if search:
            stmt = stmt.where(
                SambaCSInquiry.product_name.ilike(f"%{search}%")  # type: ignore
                | SambaCSInquiry.content.ilike(f"%{search}%")  # type: ignore
                | SambaCSInquiry.market_order_id.ilike(f"%{search}%")  # type: ignore
            )

        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def delete_batch(self, ids: List[str]) -> int:
        """여러 문의 일괄 삭제."""
        count = 0
        for _id in ids:
            deleted = await self.delete_async(_id)
            if deleted:
                count += 1
        return count
