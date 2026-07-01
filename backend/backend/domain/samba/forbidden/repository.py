"""SambaWave Forbidden word repository."""

from typing import List

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.forbidden.model import SambaForbiddenWord, SambaSettings


class SambaForbiddenWordRepository(BaseRepository[SambaForbiddenWord]):
    def __init__(self, session):
        super().__init__(session, SambaForbiddenWord)

    async def list_by_type(self, type: str) -> List[SambaForbiddenWord]:
        return await self.filter_by_async(
            type=type, order_by="created_at", order_by_desc=True
        )

    async def list_active(self, type: str) -> List[SambaForbiddenWord]:
        return await self.filter_by_async(
            type=type, is_active=True, order_by="created_at", order_by_desc=True
        )

    async def list_active_for_market(
        self, type: str, market: str
    ) -> List[SambaForbiddenWord]:
        """공통(market IS NULL) + 해당 마켓 전용 활성 단어 합산 조회.

        해당 마켓이 '금지어/삭제어 미적용' 목록(forbidden_exempt_markets)에 있으면
        빈 리스트 반환 → 옵션삭제어 등 이 통로를 쓰는 모든 적용 지점이 자동 스킵.
        """
        from sqlalchemy import or_
        from sqlmodel import select

        # 판매처 미적용 가드
        try:
            from backend.core.tenant_context import current_tenant_id

            _tid = current_tenant_id.get()
            _candidates = (
                [f"{_tid}:forbidden_exempt_markets", "forbidden_exempt_markets"]
                if _tid
                else ["forbidden_exempt_markets"]
            )
            for _ek in _candidates:
                _sr = await self.session.execute(
                    select(SambaSettings).where(SambaSettings.key == _ek)
                )
                _srow = _sr.scalars().first()
                if _srow and isinstance(_srow.value, list):
                    if market in {str(_x) for _x in _srow.value if _x}:
                        return []
                    break
        except Exception:
            pass

        stmt = (
            select(SambaForbiddenWord)
            .where(
                SambaForbiddenWord.type == type,
                SambaForbiddenWord.is_active == True,  # noqa: E712
                or_(
                    SambaForbiddenWord.market == None,  # noqa: E711
                    SambaForbiddenWord.market == market,
                ),
            )
            .order_by(SambaForbiddenWord.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


class SambaSettingsRepository(BaseRepository[SambaSettings]):
    def __init__(self, session):
        super().__init__(session, SambaSettings)
