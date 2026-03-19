"""SambaWave Category API router."""

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency

router = APIRouter(prefix="/categories", tags=["samba-categories"])


async def _get_claude_api_key(session: AsyncSession) -> str:
    """DB settings에서 Claude API Key 조회 → 없으면 env fallback."""
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository

    repo = SambaSettingsRepository(session)
    row = await repo.find_by_async(key="claude")
    if row and isinstance(row.value, dict):
        key = row.value.get("apiKey", "")
        if key:
            return key
    from backend.core.config import settings
    return settings.anthropic_api_key


class MappingCreate(BaseModel):
    source_site: str
    source_category: str
    target_mappings: Optional[Any] = None
    applied_policy_id: Optional[str] = None


class MappingUpdate(BaseModel):
    target_mappings: Optional[Any] = None
    applied_policy_id: Optional[str] = None


class TreeSave(BaseModel):
    cat1: Optional[list] = None
    cat2: Optional[Any] = None
    cat3: Optional[Any] = None
    cat4: Optional[Any] = None


class AiSuggestRequest(BaseModel):
    """AI 카테고리 매핑 요청."""
    source_site: str = Field(..., description="소싱사이트 (예: MUSINSA)")
    source_category: str = Field(..., description="소싱 카테고리 경로")
    sample_products: List[str] = Field(default_factory=list, description="대표 상품명 목록 (최대 5개)")
    target_markets: Optional[List[str]] = Field(default=None, description="매핑할 마켓 목록 (미지정 시 전체)")


def _get_service(session: AsyncSession):
    from backend.domain.samba.category.repository import (
        SambaCategoryMappingRepository,
        SambaCategoryTreeRepository,
    )
    from backend.domain.samba.category.service import SambaCategoryService

    return SambaCategoryService(
        SambaCategoryMappingRepository(session),
        SambaCategoryTreeRepository(session),
    )


# ── Mappings ──

@router.get("/mappings")
async def list_mappings(session: AsyncSession = Depends(get_read_session_dependency)):
    return await _get_service(session).list_mappings()


@router.post("/mappings", status_code=201)
async def create_mapping(
    body: MappingCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    return await _get_service(session).create_mapping(body.model_dump(exclude_unset=True))


@router.put("/mappings/{mapping_id}")
async def update_mapping(
    mapping_id: str,
    body: MappingUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    result = await _get_service(session).update_mapping(mapping_id, body.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(404, "매핑을 찾을 수 없습니다")
    return result


@router.delete("/mappings/{mapping_id}")
async def delete_mapping(
    mapping_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    if not await _get_service(session).delete_mapping(mapping_id):
        raise HTTPException(404, "매핑을 찾을 수 없습니다")
    return {"ok": True}


@router.get("/mappings/find")
async def find_mapping(
    source_site: str = Query(...),
    source_category: str = Query(...),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    return await _get_service(session).find_mapping(source_site, source_category)


@router.get("/suggest")
async def suggest_category(
    source_category: str = Query(...),
    target_market: str = Query(...),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    return _get_service(session).suggest_category(source_category, target_market)


@router.post("/ai-suggest")
async def ai_suggest_category(
    body: AiSuggestRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """Claude API를 사용한 카테고리 매핑 추천."""
    from backend.domain.samba.category.service import SambaCategoryService

    api_key = await _get_claude_api_key(session)
    try:
        result = await SambaCategoryService.ai_suggest_category(
            source_site=body.source_site,
            source_category=body.source_category,
            sample_products=body.sample_products,
            target_markets=body.target_markets,
            api_key=api_key,
        )
        return result
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/ai-suggest-bulk")
async def ai_suggest_bulk(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """미매핑 카테고리 일괄 AI 매핑 + 기존 매핑 누락 마켓 보충."""
    api_key = await _get_claude_api_key(session)
    if not api_key:
        raise HTTPException(400, "Claude API Key가 설정되지 않았습니다")
    svc = _get_service(session)
    try:
        return await svc.bulk_ai_mapping(api_key, session)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ── Category Tree ──

@router.get("/tree/{site_name}")
async def get_tree(
    site_name: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    return await _get_service(session).get_category_tree(site_name)


@router.put("/tree/{site_name}")
async def save_tree(
    site_name: str,
    body: TreeSave,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    return await _get_service(session).save_category_tree(site_name, body.model_dump())


@router.delete("/tree/{site_name}")
async def delete_tree(
    site_name: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    await _get_service(session).delete_category_tree(site_name)
    return {"ok": True}
