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
    sample_products: List[str] = Field(
        default_factory=list, description="등록 상품명 목록 (최대 5개)"
    )
    sample_tags: List[str] = Field(default_factory=list, description="상품 태그 목록")
    target_markets: Optional[List[str]] = Field(
        default=None, description="매핑할 마켓 목록 (미지정 시 전체)"
    )


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
    return await _get_service(session).create_mapping(
        body.model_dump(exclude_unset=True)
    )


@router.put("/mappings/{mapping_id}")
async def update_mapping(
    mapping_id: str,
    body: MappingUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    result = await _get_service(session).update_mapping(
        mapping_id, body.model_dump(exclude_unset=True)
    )
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
    return await _get_service(session).suggest_category(source_category, target_market)


@router.post("/ai-suggest")
async def ai_suggest_category(
    body: AiSuggestRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """Claude API를 사용한 카테고리 매핑 추천 (DB 카테고리 우선)."""
    api_key = await _get_claude_api_key(session)
    svc = _get_service(session)
    try:
        result = await svc.ai_suggest_category(
            source_site=body.source_site,
            source_category=body.source_category,
            sample_products=body.sample_products,
            sample_tags=body.sample_tags,
            target_markets=body.target_markets,
            api_key=api_key,
        )
        return result
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


class BulkAiMappingRequest(BaseModel):
    """벌크 AI 매핑 요청 — 대상 마켓 선택 + 범위 필터."""

    target_markets: Optional[List[str]] = None
    source_site: Optional[str] = None
    category_prefix: Optional[str] = None


@router.post("/ai-suggest-bulk")
async def ai_suggest_bulk(
    body: Optional[BulkAiMappingRequest] = None,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """미매핑 카테고리 일괄 AI 매핑 — 선택된 마켓/범위만 대상."""
    api_key = await _get_claude_api_key(session)
    if not api_key:
        raise HTTPException(400, "Claude API Key가 설정되지 않았습니다")
    svc = _get_service(session)
    target_markets = body.target_markets if body else None
    source_site = body.source_site if body else None
    category_prefix = body.category_prefix if body else None
    try:
        return await svc.bulk_ai_mapping(
            api_key,
            session,
            target_markets=target_markets,
            source_site=source_site,
            category_prefix=category_prefix,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


class FixBadMappingsRequest(BaseModel):
    """불량 카테고리 재매핑 요청."""

    target_markets: Optional[List[str]] = None


@router.post("/fix-bad-mappings")
async def fix_bad_mappings(
    body: Optional[FixBadMappingsRequest] = None,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """불량 카테고리 매핑 감지 및 AI 재매핑.

    패션/스포츠와 무관한 카테고리(도서/음반, 식품 등)로 잘못 매핑된 것을
    자동 감지하여 초기화한 뒤 AI로 재매핑한다.
    """
    api_key = await _get_claude_api_key(session)
    if not api_key:
        raise HTTPException(400, "Claude API Key가 설정되지 않았습니다")
    svc = _get_service(session)
    target_markets = body.target_markets if body else None
    try:
        return await svc.fix_bad_mappings(
            api_key, session, target_markets=target_markets
        )
    except Exception as e:
        raise HTTPException(500, str(e)) from e


@router.post("/markets/sync-smartstore")
async def sync_smartstore_categories(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """스마트스토어 API에서 실제 카테고리를 가져와 DB 동기화."""
    svc = _get_service(session)
    result = await svc.seed_smartstore_from_api(session)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


class MarketCheckRequest(BaseModel):
    """마켓 등록 상품 확인 요청."""

    market: str
    mapping_ids: List[str]


class BulkMarketCheckRequest(BaseModel):
    """전체 마켓 등록 상품 일괄 확인."""

    mapping_ids: List[str]


class MarketColumnDeleteRequest(BaseModel):
    """특정 마켓 카테고리 일괄 삭제 요청."""

    market: str
    mapping_ids: List[str]


class BulkDeleteRequest(BaseModel):
    """매핑 일괄 삭제 요청."""

    mapping_ids: List[str]


@router.post("/mappings/check-registered")
async def check_market_registered(
    body: MarketCheckRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """매핑 대상 카테고리의 상품이 해당 마켓에 등록되어 있는지 확인."""
    svc = _get_service(session)
    count = await svc.check_market_registered(body.mapping_ids, body.market, session)
    return {"registered_count": count}


@router.post("/mappings/check-registered-all")
async def check_all_markets_registered(
    body: BulkMarketCheckRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """모든 마켓에 대해 등록 상품 일괄 확인."""
    from backend.domain.samba.category.service import MARKET_CATEGORIES

    svc = _get_service(session)
    blocked: dict[str, int] = {}
    for market in MARKET_CATEGORIES:
        count = await svc.check_market_registered(body.mapping_ids, market, session)
        if count > 0:
            blocked[market] = count
    return {"blocked": blocked}


@router.post("/mappings/check-registered-per-mapping")
async def check_registered_per_mapping(
    body: BulkDeleteRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """매핑별로 등록 상품이 있는지 개별 확인. registered_ids에 등록 상품이 있는 매핑 ID 반환."""
    svc = _get_service(session)
    from backend.domain.samba.category.service import MARKET_CATEGORIES

    registered_ids: list[str] = []
    for mid in body.mapping_ids:
        has_product = False
        for market in MARKET_CATEGORIES:
            count = await svc.check_market_registered([mid], market, session)
            if count > 0:
                has_product = True
                break
        if has_product:
            registered_ids.append(mid)
    return {"registered_ids": registered_ids}


@router.post("/mappings/bulk-delete")
async def bulk_delete_mappings(
    body: BulkDeleteRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """매핑 일괄 삭제."""
    svc = _get_service(session)
    deleted = 0
    for mid in body.mapping_ids:
        if await svc.delete_mapping(mid):
            deleted += 1
    return {"ok": True, "deleted": deleted}


@router.post("/mappings/clear-market")
async def clear_market_column(
    body: MarketColumnDeleteRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """특정 마켓의 카테고리 매핑을 일괄 삭제 (target_mappings에서 해당 키 제거)."""
    svc = _get_service(session)
    cleared = 0
    for mid in body.mapping_ids:
        mapping = await svc.mapping_repo.get_async(mid)
        if (
            mapping
            and mapping.target_mappings
            and body.market in mapping.target_mappings
        ):
            updated = {
                k: v for k, v in mapping.target_mappings.items() if k != body.market
            }
            await svc.update_mapping(mid, {"target_mappings": updated})
            cleared += 1
    return {"ok": True, "cleared": cleared}


class EsmCrossCopyRequest(BaseModel):
    """ESM 크로스매핑 복사 요청 (지마켓↔옥션)."""

    from_market: str = Field(default="gmarket", description="원본 마켓")
    to_market: str = Field(default="auction", description="대상 마켓")
    mapping_ids: Optional[List[str]] = Field(
        default=None, description="대상 매핑 ID (미지정 시 전체)"
    )


@router.post("/mappings/copy-esm")
async def copy_esm_cross_mapping(
    body: EsmCrossCopyRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """지마켓↔옥션 카테고리 매핑을 크로스매핑으로 복사."""
    valid_markets = {"gmarket", "auction"}
    if body.from_market not in valid_markets or body.to_market not in valid_markets:
        raise HTTPException(400, "ESM 크로스매핑은 gmarket ↔ auction만 지원합니다")
    if body.from_market == body.to_market:
        raise HTTPException(400, "원본과 대상 마켓이 같습니다")
    svc = _get_service(session)
    result = await svc.copy_esm_cross_mapping(
        from_market=body.from_market,
        to_market=body.to_market,
        mapping_ids=body.mapping_ids,
    )
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


# ── Market Category Seed ──


@router.get("/markets/counts")
async def get_market_category_counts(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """마켓별 DB 카테고리 수 반환."""
    from sqlmodel import select
    from backend.domain.samba.category.model import SambaCategoryTree

    result = await session.execute(select(SambaCategoryTree))
    counts: dict[str, int] = {}
    for tree in result.scalars().all():
        counts[tree.site_name] = len(tree.cat1) if tree.cat1 else 0
    return counts


@router.post("/markets/seed")
async def seed_market_categories(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """마켓 카테고리 데이터를 DB에 동기화 (하드코딩 → DB)."""
    svc = _get_service(session)
    result = await svc.seed_market_categories()
    return {"ok": True, "markets": result}


@router.post("/markets/sync/{market_type}")
async def sync_market_categories(
    market_type: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """마켓 API에서 실시간 카테고리를 조회하여 DB에 동기화."""
    svc = _get_service(session)
    try:
        result = await svc.sync_market_from_api(market_type, session)
        return {"ok": True, "market": market_type, **result}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(500, f"카테고리 동기화 중 오류: {e}") from e


@router.post("/markets/sync-all")
async def sync_all_market_categories(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """모든 마켓의 카테고리를 API에서 조회하여 일괄 동기화."""
    svc = _get_service(session)
    results = await svc.sync_all_markets(session)
    return {"ok": True, "results": results}


@router.post("/markets/ai-seed/{market_type}")
async def ai_seed_market_categories(
    market_type: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """AI로 마켓 카테고리 전체 목록을 생성하여 DB에 저장 (계정 없이 사용 가능)."""
    api_key = await _get_claude_api_key(session)
    if not api_key:
        raise HTTPException(400, "Claude API Key가 설정되지 않았습니다")
    svc = _get_service(session)
    try:
        result = await svc.seed_market_via_ai(market_type, api_key)
        return {"ok": True, **result}
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@router.post("/markets/ai-seed-all")
async def ai_seed_all_market_categories(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """모든 마켓의 카테고리를 AI로 일괄 생성 (계정 없이 사용 가능)."""
    api_key = await _get_claude_api_key(session)
    if not api_key:
        raise HTTPException(400, "Claude API Key가 설정되지 않았습니다")
    svc = _get_service(session)
    results = await svc.seed_all_markets_via_ai(api_key)
    return {"ok": True, "results": results}


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
