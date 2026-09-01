"""회귀 테스트 (C1) — 휴지통(soft-delete)된 상품은 테트리스 자동배정 대상에서 제외돼야 한다.

배경: 상품을 휴지통으로 이동하면 registered_accounts가 비워진다(마켓에서 실제로
내려갔으므로). 이 때문에 `_get_product_ids_for_assign`이 "한 번도 등록된 적 없는
상품"과 "휴지통에 버려진 상품"을 구분하지 못하고 후자를 다시 마켓에 자동 등록하는
사고가 있었다(C1). deleted_at IS NULL 조건 추가로 고쳤다 — 이 테스트는 그 조건이
실제로 동작하는지 검증한다.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlmodel import delete as sa_delete
from ulid import ULID

from backend.db.orm import get_write_sessionmaker
from backend.domain.samba.collector.model import SambaCollectedProduct
from backend.domain.samba.tetris.service import SambaTetrisService


@pytest.mark.asyncio
async def test_trashed_product_excluded_from_assign_targets(db_session):
    """휴지통(deleted_at IS NOT NULL) 상품은 배정 대상 목록에 나오지 않아야 한다."""
    brand = f"테트리스휴지통테스트_{ULID()}"
    source_site = "musinsa"

    active = SambaCollectedProduct(
        source_site=source_site,
        name="활성 상품",
        brand=brand,
    )
    trashed = SambaCollectedProduct(
        source_site=source_site,
        name="휴지통 상품",
        brand=brand,
        deleted_at=datetime.now(timezone.utc),
    )
    db_session.add(active)
    db_session.add(trashed)
    await db_session.commit()
    await db_session.refresh(active)
    await db_session.refresh(trashed)

    try:
        svc = SambaTetrisService(repo=None, session=db_session)  # type: ignore[arg-type]
        ids = await svc._get_product_ids_for_assign(
            tenant_id=None,
            source_site=source_site,
            brand_name=brand,
            market_account_id="ma_some_account",
        )

        assert active.id in ids
        assert trashed.id not in ids
    finally:
        Session = get_write_sessionmaker()
        async with Session() as session:
            await session.execute(
                sa_delete(SambaCollectedProduct).where(
                    SambaCollectedProduct.id.in_([active.id, trashed.id])
                )
            )
            await session.commit()
