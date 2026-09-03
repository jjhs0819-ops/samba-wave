"""SambaWave 주문건 소싱처 최저가 탐색 API router.

- POST /samba/price-scout/batch        : 여러 주문 일괄 스캔 (최대 50건, 동시 3)
- POST /samba/price-scout/{order_id}   : 단건 스캔 (24시간 캐시, force=true 로 무시)
- GET  /samba/price-scout?order_ids=.. : 캐시만 조회 (스캔 안 함 — 목록 뱃지용)
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.order.model import SambaOrder
from backend.domain.samba.price_scout.model import SambaOrderPriceScan
from backend.domain.samba.price_scout.service import scout_order
from backend.domain.samba.tenant.middleware import get_optional_tenant_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/price-scout", tags=["samba-price-scout"])

# 캐시 유효 시간 — 이 안이면 재스캔 없이 캐시 반환 (force=true 로 무시 가능)
_CACHE_TTL = timedelta(hours=24)

# 배치 스캔 한도 — 소싱처 부하 방지
_BATCH_MAX = 50
_BATCH_CONCURRENCY = 3


class PriceScoutBatchBody(BaseModel):
    order_ids: list[str]


def _tenant_clause(tenant_id: Optional[str]):
    """tenant 격리 조건 — 본인 테넌트 또는 미지정(NULL) 행만."""
    return or_(
        SambaOrder.tenant_id == tenant_id,
        SambaOrder.tenant_id == None,  # noqa: E711
    )


def _is_cache_fresh(scan: SambaOrderPriceScan) -> bool:
    """캐시가 24시간 이내인지."""
    if scan.scanned_at is None:
        return False
    scanned = scan.scanned_at
    if scanned.tzinfo is None:
        scanned = scanned.replace(tzinfo=timezone.utc)
    return datetime.now(tz=timezone.utc) - scanned < _CACHE_TTL


async def _load_order(
    session: AsyncSession, order_id: str, tenant_id: Optional[str]
) -> Optional[SambaOrder]:
    stmt = select(SambaOrder).where(SambaOrder.id == order_id)
    if tenant_id is not None:
        stmt = stmt.where(_tenant_clause(tenant_id))
    return (await session.execute(stmt)).scalars().first()


async def _upsert_scan(
    session: AsyncSession, order: SambaOrder, scout: dict
) -> SambaOrderPriceScan:
    """스캔 결과를 order_id 기준 1행으로 upsert (commit 은 호출측에서)."""
    now = datetime.now(tz=timezone.utc)
    existing = (
        (
            await session.execute(
                select(SambaOrderPriceScan).where(
                    SambaOrderPriceScan.order_id == order.id
                )
            )
        )
        .scalars()
        .first()
    )
    if existing is None:
        existing = SambaOrderPriceScan(order_id=order.id, tenant_id=order.tenant_id)
        session.add(existing)

    existing.tenant_id = order.tenant_id
    existing.model_code = scout.get("model_code")
    existing.base_cost = scout.get("base_cost")
    existing.best_site = scout.get("best_site")
    existing.best_price = scout.get("best_price")
    existing.best_url = scout.get("best_url")
    existing.results = scout.get("results")
    existing.suspect = bool(scout.get("suspect"))
    existing.error = scout.get("error")
    existing.scanned_at = now
    existing.updated_at = now
    return existing


@router.get("")
async def get_price_scans(
    order_ids: str = Query(..., description="쉼표구분 주문 ID 목록"),
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    """캐시된 스캔 결과만 조회 (스캔 수행 안 함) — {order_id: scanRow} 맵."""
    ids = [s.strip() for s in order_ids.split(",") if s.strip()]
    if not ids:
        return {}
    stmt = select(SambaOrderPriceScan).where(col(SambaOrderPriceScan.order_id).in_(ids))
    if tenant_id is not None:
        stmt = stmt.where(
            or_(
                SambaOrderPriceScan.tenant_id == tenant_id,
                SambaOrderPriceScan.tenant_id == None,  # noqa: E711
            )
        )
    rows = (await session.execute(stmt)).scalars().all()
    return {row.order_id: row for row in rows}


@router.post("/batch")
async def scan_price_batch(
    body: PriceScoutBatchBody,
    session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    """여러 주문 일괄 스캔 — 최대 50건, 소싱처 부하 방지로 동시 3건.

    캐시가 24시간 이내인 주문은 재스캔 없이 캐시를 쓴다.
    반환: {order_id: {cached, scan} | {skipped} | {error}}
    """
    ids = list(dict.fromkeys(body.order_ids))  # 중복 제거(순서 유지)
    if not ids:
        return {}
    if len(ids) > _BATCH_MAX:
        raise HTTPException(
            status_code=400, detail=f"한 번에 최대 {_BATCH_MAX}건까지 스캔할 수 있습니다"
        )

    # 주문 일괄 로드 (tenant 격리)
    stmt = select(SambaOrder).where(col(SambaOrder.id).in_(ids))
    if tenant_id is not None:
        stmt = stmt.where(_tenant_clause(tenant_id))
    orders = {o.id: o for o in (await session.execute(stmt)).scalars().all()}

    # 기존 캐시 일괄 로드
    cache_stmt = select(SambaOrderPriceScan).where(
        col(SambaOrderPriceScan.order_id).in_(ids)
    )
    caches = {
        c.order_id: c for c in (await session.execute(cache_stmt)).scalars().all()
    }

    out: dict[str, object] = {}
    to_scan: list[SambaOrder] = []
    for oid in ids:
        order = orders.get(oid)
        if order is None:
            out[oid] = {"error": "주문 없음"}
            continue
        cache = caches.get(oid)
        if cache is not None and _is_cache_fresh(cache):
            out[oid] = {"cached": True, "scan": cache}
            continue
        to_scan.append(order)

    # 스캔(네트워크)만 동시 실행 — DB 반영은 아래에서 순차 (AsyncSession 동시쓰기 금지)
    sem = asyncio.Semaphore(_BATCH_CONCURRENCY)

    async def _scan_one(order: SambaOrder) -> dict:
        async with sem:
            return await scout_order(order)

    scan_results = await asyncio.gather(
        *[_scan_one(o) for o in to_scan], return_exceptions=True
    )

    for order, scout in zip(to_scan, scan_results):
        if isinstance(scout, BaseException):
            logger.warning(f"[최저가탐색] 배치 스캔 실패 — order={order.id}: {scout!r}")
            out[order.id] = {"error": str(scout)}
            continue
        if "skipped" in scout:
            out[order.id] = scout
            continue
        row = await _upsert_scan(session, order, scout)
        out[order.id] = {"cached": False, "scan": row}

    await session.commit()
    return out


@router.post("/{order_id}")
async def scan_price_single(
    order_id: str,
    force: bool = Query(False, description="true 면 24시간 캐시 무시하고 재스캔"),
    session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    """단건 스캔 — 캐시가 24시간 이내면 캐시 반환, 아니면 스캔 후 upsert."""
    order = await _load_order(session, order_id, tenant_id)
    if order is None:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다")

    existing = (
        (
            await session.execute(
                select(SambaOrderPriceScan).where(
                    SambaOrderPriceScan.order_id == order_id
                )
            )
        )
        .scalars()
        .first()
    )
    if existing is not None and not force and _is_cache_fresh(existing):
        return {"cached": True, "scan": existing}

    scout = await scout_order(order)
    if "skipped" in scout:
        return scout

    row = await _upsert_scan(session, order, scout)
    await session.commit()
    await session.refresh(row)
    return {"cached": False, "scan": row}
