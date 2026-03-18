"""SambaWave Policy API router."""

import logging
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.policy.model import SambaDetailTemplate, SambaNameRule, SambaPolicy
from backend.domain.samba.policy.repository import SambaPolicyRepository
from backend.domain.samba.policy.service import SambaPolicyService
from backend.dtos.samba.policy import PolicyCreate, PolicyUpdate, PriceCalculateRequest
from backend.utils.s3 import build_s3_key, delete_s3_object, generate_presigned_put_url, get_public_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/policies", tags=["samba-policies"])


def _get_service(session: AsyncSession) -> SambaPolicyService:
    return SambaPolicyService(SambaPolicyRepository(session))


@router.get("", response_model=list[SambaPolicy])
async def list_policies(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_service(session)
    return await svc.list_policies(skip=skip, limit=limit)


# ── Detail Templates ──────────────────────────────────────────────────────────
# 정적 경로를 /{policy_id} 파라미터 경로보다 먼저 등록해야 경로 충돌 방지

@router.get("/detail-templates", response_model=list[SambaDetailTemplate])
async def list_detail_templates(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """상세페이지 템플릿 목록 조회."""
    from backend.domain.shared.base_repository import BaseRepository
    repo = BaseRepository(session, SambaDetailTemplate)
    return await repo.list_async(skip=skip, limit=limit, order_by="-created_at")


@router.get("/detail-templates/{template_id}", response_model=SambaDetailTemplate)
async def get_detail_template(
    template_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """상세페이지 템플릿 단건 조회."""
    from backend.domain.shared.base_repository import BaseRepository
    repo = BaseRepository(session, SambaDetailTemplate)
    tpl = await repo.get_async(template_id)
    if not tpl:
        raise HTTPException(404, "템플릿을 찾을 수 없습니다")
    return tpl


@router.post("/detail-templates", response_model=SambaDetailTemplate, status_code=201)
async def create_detail_template(
    body: dict = Body(...),
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """상세페이지 템플릿 생성."""
    from backend.domain.shared.base_repository import BaseRepository
    repo = BaseRepository(session, SambaDetailTemplate)
    return await repo.create_async(**body)


@router.put("/detail-templates/{template_id}", response_model=SambaDetailTemplate)
async def update_detail_template(
    template_id: str,
    body: dict = Body(...),
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """상세페이지 템플릿 수정."""
    from backend.domain.shared.base_repository import BaseRepository
    repo = BaseRepository(session, SambaDetailTemplate)
    tpl = await repo.update_async(template_id, **body)
    if not tpl:
        raise HTTPException(404, "템플릿을 찾을 수 없습니다")
    return tpl


@router.delete("/detail-templates/{template_id}")
async def delete_detail_template(
    template_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """상세페이지 템플릿 삭제."""
    from backend.domain.shared.base_repository import BaseRepository
    repo = BaseRepository(session, SambaDetailTemplate)
    # 삭제 전 S3 이미지 정리
    tpl = await repo.get_async(template_id)
    if tpl:
        for key in [tpl.top_image_s3_key, tpl.bottom_image_s3_key]:
            if key:
                try:
                    delete_s3_object(key)
                except Exception:
                    logger.warning("S3 삭제 실패: %s", key)
    deleted = await repo.delete_async(template_id)
    if not deleted:
        raise HTTPException(404, "템플릿을 찾을 수 없습니다")
    return {"ok": True}


# ── Detail Template S3 이미지 업로드 ─────────────────────────────────────────


class PresignedUrlRequest(BaseModel):
    position: Literal["top", "bottom"]
    content_type: str = "image/png"


class ConfirmUploadRequest(BaseModel):
    position: Literal["top", "bottom"]
    s3_key: str


@router.post("/detail-templates/{template_id}/presigned-url")
async def get_presigned_url(
    template_id: str,
    body: PresignedUrlRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """Presigned PUT URL 발급."""
    from backend.domain.shared.base_repository import BaseRepository
    repo = BaseRepository(session, SambaDetailTemplate)
    tpl = await repo.get_async(template_id)
    if not tpl:
        raise HTTPException(404, "템플릿을 찾을 수 없습니다")

    # content_type에서 확장자 추출
    ext = body.content_type.split("/")[-1]
    if ext == "jpeg":
        ext = "jpg"
    s3_key = build_s3_key(template_id, body.position, ext)
    upload_url = generate_presigned_put_url(s3_key, body.content_type)
    return {"upload_url": upload_url, "s3_key": s3_key}


@router.post("/detail-templates/{template_id}/confirm-upload")
async def confirm_upload(
    template_id: str,
    body: ConfirmUploadRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """S3 업로드 완료 후 DB에 s3_key 저장."""
    from backend.domain.shared.base_repository import BaseRepository
    repo = BaseRepository(session, SambaDetailTemplate)
    tpl = await repo.get_async(template_id)
    if not tpl:
        raise HTTPException(404, "템플릿을 찾을 수 없습니다")

    # 기존 이미지 삭제
    old_key = tpl.top_image_s3_key if body.position == "top" else tpl.bottom_image_s3_key
    if old_key:
        try:
            delete_s3_object(old_key)
        except Exception:
            logger.warning("기존 S3 이미지 삭제 실패: %s", old_key)

    # DB 업데이트
    field = "top_image_s3_key" if body.position == "top" else "bottom_image_s3_key"
    updated = await repo.update_async(template_id, **{field: body.s3_key})
    return updated


# ── Name Rules ────────────────────────────────────────────────────────────────

@router.get("/name-rules", response_model=list[SambaNameRule])
async def list_name_rules(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """상품/옵션명 규칙 목록 조회."""
    from backend.domain.shared.base_repository import BaseRepository
    repo = BaseRepository(session, SambaNameRule)
    return await repo.list_async(skip=skip, limit=limit, order_by="-created_at")


@router.get("/name-rules/{rule_id}", response_model=SambaNameRule)
async def get_name_rule(
    rule_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """상품/옵션명 규칙 단건 조회."""
    from backend.domain.shared.base_repository import BaseRepository
    repo = BaseRepository(session, SambaNameRule)
    rule = await repo.get_async(rule_id)
    if not rule:
        raise HTTPException(404, "규칙을 찾을 수 없습니다")
    return rule


@router.post("/name-rules", response_model=SambaNameRule, status_code=201)
async def create_name_rule(
    body: dict = Body(...),
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """상품/옵션명 규칙 생성."""
    from backend.domain.shared.base_repository import BaseRepository
    repo = BaseRepository(session, SambaNameRule)
    return await repo.create_async(**body)


@router.put("/name-rules/{rule_id}", response_model=SambaNameRule)
async def update_name_rule(
    rule_id: str,
    body: dict = Body(...),
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """상품/옵션명 규칙 수정."""
    from backend.domain.shared.base_repository import BaseRepository
    repo = BaseRepository(session, SambaNameRule)
    rule = await repo.update_async(rule_id, **body)
    if not rule:
        raise HTTPException(404, "규칙을 찾을 수 없습니다")
    return rule


@router.delete("/name-rules/{rule_id}")
async def delete_name_rule(
    rule_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """상품/옵션명 규칙 삭제."""
    from backend.domain.shared.base_repository import BaseRepository
    repo = BaseRepository(session, SambaNameRule)
    deleted = await repo.delete_async(rule_id)
    if not deleted:
        raise HTTPException(404, "규칙을 찾을 수 없습니다")
    return {"ok": True}


# ── Policy CRUD (파라미터 경로는 정적 경로 뒤에 등록) ─────────────────────────

@router.get("/{policy_id}", response_model=SambaPolicy)
async def get_policy(
    policy_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_service(session)
    policy = await svc.get_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="정책을 찾을 수 없습니다")
    return policy


@router.post("", response_model=SambaPolicy, status_code=201)
async def create_policy(
    body: PolicyCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _get_service(session)
    return await svc.create_policy(body.model_dump(exclude_unset=True))


@router.put("/{policy_id}", response_model=SambaPolicy)
async def update_policy(
    policy_id: str,
    body: PolicyUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _get_service(session)
    policy = await svc.update_policy(policy_id, body.model_dump(exclude_unset=True))
    if not policy:
        raise HTTPException(status_code=404, detail="정책을 찾을 수 없습니다")
    return policy


@router.delete("/{policy_id}")
async def delete_policy(
    policy_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _get_service(session)
    deleted = await svc.delete_policy(policy_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="정책을 찾을 수 없습니다")
    return {"ok": True}


@router.post("/{policy_id}/calculate-price")
async def calculate_price(
    policy_id: str,
    body: PriceCalculateRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_service(session)
    return await svc.get_price_preview(policy_id, body.cost, body.fee_rate)
