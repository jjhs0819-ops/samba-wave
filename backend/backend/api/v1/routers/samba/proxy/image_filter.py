"""이미지 필터링 관련 엔드포인트."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_write_session_dependency
from backend.utils.logger import logger

router = APIRouter(tags=["samba-proxy"])


@router.post("/image-filter/filter")
async def filter_product_images(
    request: dict[str, Any],
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """상품 이미지 자동 필터링 — 이미지컷만 남기고 모델컷/연출컷/배너 제거."""
    from backend.domain.samba.image.image_filter_service import ImageFilterService

    svc = ImageFilterService(session)
    product_ids: list[str] = request.get("product_ids", [])
    filter_id: str = request.get("filter_id", "")
    scope: str = request.get("scope", "images")  # images | detail | all
    method: str = request.get("method", "claude")  # claude | clip

    # filter_id로 요청 시 해당 그룹의 상품 ID 조회 (product_ids 우선)
    if filter_id and not product_ids:
        try:
            result = await svc.filter_by_group(filter_id, scope=scope, method=method)
            return result
        except Exception as exc:
            logger.error(f"[이미지필터] 그룹 필터링 실패: {exc}")
            return {"success": False, "message": str(exc)[:300]}

    if not product_ids:
        return {"success": False, "message": "product_ids 또는 filter_id를 입력하세요."}

    try:
        result = await svc.batch_filter(product_ids, scope=scope, method=method)
        return result
    except Exception as exc:
        logger.error(f"[이미지필터] 배치 필터링 실패: {exc}")
        return {"success": False, "message": str(exc)[:300]}


@router.post("/image-filter/compare")
async def compare_image_filter_methods(
    request: dict[str, Any],
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """Claude vs CLIP 정확도 비교 — 같은 이미지에 둘 다 돌려서 결과 비교."""
    from backend.domain.samba.image.image_filter_service import ImageFilterService

    svc = ImageFilterService(session)
    urls: list[str] = request.get("urls", [])
    product_id: str = request.get("product_id", "")

    # product_id가 있으면 해당 상품 이미지 URL 조회
    if product_id and not urls:
        from backend.domain.samba.collector.repository import (
            SambaCollectedProductRepository,
        )

        repo = SambaCollectedProductRepository(session)
        product = await repo.get_async(product_id)
        if not product:
            return {"success": False, "message": "상품을 찾을 수 없습니다."}
        urls = product.images or []

    if not urls:
        return {"success": False, "message": "urls 또는 product_id를 입력하세요."}

    try:
        result = await svc.compare_methods(urls)
        return {"success": True, **result}
    except Exception as exc:
        logger.error(f"[이미지필터] 비교 실패: {exc}")
        return {"success": False, "message": str(exc)[:300]}
