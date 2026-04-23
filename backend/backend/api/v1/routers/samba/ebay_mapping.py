"""SambaWave eBay 매핑 API router."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency

router = APIRouter(prefix="/ebay-mapping", tags=["samba-ebay-mapping"])


class MappingCreate(BaseModel):
    category: str  # color | material | origin | sex | type
    kr_value: str
    en_value: str


class MappingUpdate(BaseModel):
    en_value: Optional[str] = None


class TranslateRequest(BaseModel):
    category: str
    kr_value: str


@router.get("/list")
async def list_mappings(
    category: Optional[str] = None,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """전체 매핑 또는 카테고리별 매핑 리스트 조회."""
    from backend.domain.samba.ebay_mapping.repository import (
        SambaEbayMappingRepository,
    )

    repo = SambaEbayMappingRepository(session)
    rows = await repo.list_by_category(category)
    return {
        "total": len(rows),
        "items": [
            {
                "id": r.id,
                "category": r.category,
                "kr_value": r.kr_value,
                "en_value": r.en_value,
                "source": r.source,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ],
    }


@router.post("/")
async def create_mapping(
    body: MappingCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """매핑 추가 (source=manual)."""
    from backend.domain.samba.ebay_mapping.repository import (
        SambaEbayMappingRepository,
    )

    repo = SambaEbayMappingRepository(session)
    row = await repo.upsert(
        body.category, body.kr_value, body.en_value, source="manual"
    )
    await session.commit()
    return {
        "id": row.id,
        "category": row.category,
        "kr_value": row.kr_value,
        "en_value": row.en_value,
        "source": row.source,
    }


@router.put("/{mapping_id}")
async def update_mapping(
    mapping_id: str,
    body: MappingUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """매핑 영문값 수정 (source=manual로 변경)."""
    from backend.domain.samba.ebay_mapping.model import SambaEbayMapping
    from sqlmodel import select

    stmt = select(SambaEbayMapping).where(SambaEbayMapping.id == mapping_id)
    result = await session.execute(stmt)
    row = result.scalars().first()
    if not row:
        raise HTTPException(404, "매핑을 찾을 수 없습니다")
    if body.en_value is not None:
        row.en_value = body.en_value
    row.source = "manual"
    from datetime import datetime, timezone

    row.updated_at = datetime.now(tz=timezone.utc)
    session.add(row)
    await session.commit()
    return {
        "id": row.id,
        "category": row.category,
        "kr_value": row.kr_value,
        "en_value": row.en_value,
        "source": row.source,
    }


@router.delete("/{mapping_id}")
async def delete_mapping(
    mapping_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """매핑 삭제."""
    from backend.domain.samba.ebay_mapping.repository import (
        SambaEbayMappingRepository,
    )

    repo = SambaEbayMappingRepository(session)
    ok = await repo.delete(mapping_id)
    if not ok:
        raise HTTPException(404, "매핑을 찾을 수 없습니다")
    await session.commit()
    return {"success": True}


@router.post("/translate")
async def translate(
    body: TranslateRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """한글 값을 영문으로 변환 (DB → Claude 순서)."""
    from backend.domain.samba.ebay_mapping.service import SambaEbayMappingService

    svc = SambaEbayMappingService(session)
    en = await svc.translate(body.category, body.kr_value)
    await session.commit()  # Claude 폴백 결과 DB 캐싱
    return {"kr_value": body.kr_value, "en_value": en}


@router.post("/seed")
async def seed_defaults(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """기본 시드 데이터 삽입 (이미 있으면 건너뜀)."""
    from backend.domain.samba.ebay_mapping.service import SambaEbayMappingService

    svc = SambaEbayMappingService(session)
    added = await svc.seed_defaults()
    await session.commit()
    return {"added": added}


@router.post("/cleanup-invalid")
async def cleanup_invalid_mappings(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """잘못된 ai 매핑 캐시 정리 (Claude 거부 응답 등)."""
    from backend.domain.samba.ebay_mapping.model import SambaEbayMapping
    from backend.domain.samba.ebay_mapping.service import SambaEbayMappingService
    from sqlmodel import select

    svc = SambaEbayMappingService(session)
    stmt = select(SambaEbayMapping).where(SambaEbayMapping.source == "ai")
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    deleted = []
    for r in rows:
        if svc._is_invalid_translation(r.en_value):
            deleted.append(
                {
                    "category": r.category,
                    "kr_value": r.kr_value,
                    "en_value": r.en_value,
                }
            )
            await session.delete(r)
    await session.commit()
    return {"deleted_count": len(deleted), "deleted": deleted}
