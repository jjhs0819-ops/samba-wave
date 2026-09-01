"""회귀 테스트 (I4) — 재수집(upsert)이 휴지통 상품을 조용히 되살리거나 덮어쓰지 않는다.

배경: `SambaCollectorService.create_collected_product`는 (source_site,
site_product_id) 유니크 제약 충돌(IntegrityError) 시 기존 row를 찾아 그 자리에서
업데이트하는 upsert 폴백을 갖고 있다. 이 폴백이 `deleted_at`을 확인하지 않아,
휴지통에 있는 상품이 자동 재수집 잡에 의해 내용이 조용히 덮어써지는 사고가
있었다(I4). 트래시는 사용자의 명시적 행동이고 복구도 명시적 액션으로만 이뤄져야
한다는 원칙에 따라, 이제 매칭된 기존 row가 deleted_at IS NOT NULL이면 upsert를
skip하고 None을 반환한다(새 row도 만들 수 없음 — 동일 유니크 제약에 걸림).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlmodel import delete as sa_delete
from ulid import ULID

from backend.domain.samba.collector.model import SambaCollectedProduct
from backend.domain.samba.collector.repository import (
    SambaCollectedProductRepository,
    SambaSearchFilterRepository,
)
from backend.domain.samba.collector.service import SambaCollectorService


@pytest.mark.asyncio
async def test_recollect_trashed_product_is_skipped_not_resurrected(db_session):
    source_site = "musinsa"
    site_product_id = f"trash-upsert-test-{ULID()}"

    svc = SambaCollectorService(
        SambaSearchFilterRepository(db_session),
        SambaCollectedProductRepository(db_session),
    )

    original = SambaCollectedProduct(
        source_site=source_site,
        site_product_id=site_product_id,
        name="원본 상품명",
        images=["https://example.com/a.jpg"],
    )
    db_session.add(original)
    await db_session.commit()
    await db_session.refresh(original)

    try:
        # 사용자가 휴지통으로 이동 — 명시적 액션 시뮬레이션.
        original.deleted_at = datetime.now(timezone.utc)
        db_session.add(original)
        await db_session.commit()

        # 자동 재수집이 같은 (source_site, site_product_id)로 다시 들어옴 — 이름이
        # 다른 새 데이터를 보내 "조용한 덮어쓰기"가 실제로 일어나는지 판별 가능하게 함.
        result = await svc.create_collected_product(
            {
                "source_site": source_site,
                "site_product_id": site_product_id,
                "name": "재수집으로 덮어써지면 안 되는 새 이름",
                "images": ["https://example.com/b.jpg"],
            }
        )

        assert result is None, "휴지통 상품 upsert는 None을 반환해 skip해야 한다"

        await db_session.refresh(original)
        assert original.name == "원본 상품명", "휴지통 상품 내용이 조용히 덮어써짐"
        assert original.deleted_at is not None, "휴지통 상품이 조용히 복구(un-trash)됨"
    finally:
        await db_session.execute(
            sa_delete(SambaCollectedProduct).where(
                SambaCollectedProduct.id == original.id
            )
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_recollect_active_product_still_updates_normally(db_session):
    """회귀 방지 대조군 — 휴지통이 아닌 정상 상품은 기존과 동일하게 upsert 업데이트된다."""
    source_site = "musinsa"
    site_product_id = f"active-upsert-test-{ULID()}"

    svc = SambaCollectorService(
        SambaSearchFilterRepository(db_session),
        SambaCollectedProductRepository(db_session),
    )

    original = SambaCollectedProduct(
        source_site=source_site,
        site_product_id=site_product_id,
        name="원본 상품명",
        images=["https://example.com/a.jpg"],
    )
    db_session.add(original)
    await db_session.commit()
    await db_session.refresh(original)

    try:
        result = await svc.create_collected_product(
            {
                "source_site": source_site,
                "site_product_id": site_product_id,
                "name": "정상 재수집 갱신된 이름",
                "images": ["https://example.com/b.jpg"],
            }
        )

        assert result is not None
        assert result.id == original.id
        assert result.name == "정상 재수집 갱신된 이름"
    finally:
        await db_session.execute(
            sa_delete(SambaCollectedProduct).where(
                SambaCollectedProduct.id == original.id
            )
        )
        await db_session.commit()
