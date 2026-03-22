"""SambaWave Forbidden Word API router."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency

router = APIRouter(prefix="/forbidden", tags=["samba-forbidden"])


class WordCreate(BaseModel):
    word: str
    type: str = "forbidden"  # forbidden | deletion
    scope: str = "title"  # title | description | both
    group_id: Optional[str] = None
    is_active: bool = True


class WordUpdate(BaseModel):
    word: Optional[str] = None
    type: Optional[str] = None
    scope: Optional[str] = None
    is_active: Optional[bool] = None


class ValidateRequest(BaseModel):
    name: str


def _get_service(session: AsyncSession):
    from backend.domain.samba.forbidden.repository import (
        SambaForbiddenWordRepository,
        SambaSettingsRepository,
    )
    from backend.domain.samba.forbidden.service import SambaForbiddenService

    return SambaForbiddenService(
        SambaForbiddenWordRepository(session),
        SambaSettingsRepository(session),
    )


@router.get("/words")
async def list_words(
    type: Optional[str] = None,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_service(session)
    if type:
        return await svc.list_by_type(type)
    return await svc.list_words()


@router.post("/words", status_code=201)
async def create_word(
    body: WordCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    return await _get_service(session).create_word(body.model_dump(exclude_unset=True))


class BulkWordsRequest(BaseModel):
    type: str  # forbidden | deletion
    words: list[str]


@router.post("/words/bulk", status_code=201)
async def bulk_save_words(
    body: BulkWordsRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """기존 타입의 단어를 전부 삭제 후 새 단어 벌크 저장 (단일 트랜잭션)."""
    from sqlmodel import delete, select
    from backend.domain.samba.forbidden.model import SambaForbiddenWord

    # 해당 타입 전체 삭제 (단일 쿼리)
    await session.exec(delete(SambaForbiddenWord).where(SambaForbiddenWord.type == body.type))

    # 새 단어 일괄 추가 (중복 제거)
    created = 0
    seen: set[str] = set()
    for word in body.words:
        w = word.strip()
        if not w or w.lower() in seen:
            continue
        seen.add(w.lower())
        session.add(SambaForbiddenWord(word=w, type=body.type, scope="all", is_active=True))
        created += 1

    await session.commit()
    return {"ok": True, "created": created}


@router.put("/words/{word_id}")
async def update_word(
    word_id: str,
    body: WordUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    result = await _get_service(session).update_word(word_id, body.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(404, "단어를 찾을 수 없습니다")
    return result


@router.put("/words/{word_id}/toggle")
async def toggle_word(
    word_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    result = await _get_service(session).toggle_word(word_id)
    if not result:
        raise HTTPException(404, "단어를 찾을 수 없습니다")
    return result


@router.delete("/words/{word_id}")
async def delete_word(
    word_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    if not await _get_service(session).delete_word(word_id):
        raise HTTPException(404, "단어를 찾을 수 없습니다")
    return {"ok": True}


@router.post("/validate")
async def validate_product_name(
    body: ValidateRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_service(session)
    return await svc.validate_product({"name": body.name})


@router.post("/clean")
async def clean_product_name(
    body: ValidateRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_service(session)
    return {"clean_name": await svc.clean_product_name(body.name)}


# ── Settings (generic key-value store) ──

@router.get("/settings/{key}")
async def get_setting(
    key: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_service(session)
    result = await svc.get_setting(key)
    # None이면 빈 dict 반환 (프론트에서 .catch(() => null) 호환)
    return result if result is not None else {}


@router.put("/settings/{key}")
async def save_setting(
    key: str,
    body: dict,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _get_service(session)
    return await svc.save_setting(key, body.get("value"))


@router.get("/tag-banned-words")
async def get_tag_banned_words(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """태그 금지어 통합 조회: 소싱처 + 수집 브랜드 + API 거부 태그."""
    from sqlmodel import select, func
    from backend.domain.samba.collector.model import SambaCollectedProduct

    svc = _get_service(session)

    # 1. API 거부 태그 (DB 누적)
    rejected = await svc.get_setting("smartstore_banned_tags")
    rejected_tags: list[str] = rejected if isinstance(rejected, list) else []

    # 2. 수집된 브랜드 (distinct)
    stmt = select(SambaCollectedProduct.brand).where(
        SambaCollectedProduct.brand.isnot(None),
        SambaCollectedProduct.brand != "",
    ).distinct().limit(500)
    result = await session.exec(stmt)
    brands = sorted(set(b for b in result.all() if b and len(b.strip()) >= 2))

    # 3. 소싱처 (고정)
    source_sites = [
        "MUSINSA", "무신사", "KREAM", "크림", "ABCmart", "ABC마트",
        "Nike", "나이키", "Adidas", "아디다스", "올리브영", "OliveYoung",
        "SSG", "신세계", "롯데온", "LOTTEON", "GSShop", "GS샵",
        "eBay", "이베이", "Zara", "자라", "FashionPlus", "패션플러스",
        "GrandStage", "그랜드스테이지", "OKmall", "ElandMall", "이랜드몰",
        "SSF", "SSF샵",
    ]

    return {
        "rejected": rejected_tags,
        "brands": brands,
        "source_sites": source_sites,
    }
