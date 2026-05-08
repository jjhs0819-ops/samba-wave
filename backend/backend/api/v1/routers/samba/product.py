"""SambaWave Product API router."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.product.model import SambaProduct
from backend.domain.samba.product.repository import SambaProductRepository
from backend.domain.samba.product.service import SambaProductService
from backend.domain.samba.tenant.middleware import get_optional_tenant_id
from backend.dtos.samba.product import ProductCreate, ProductUpdate

router = APIRouter(prefix="/products", tags=["samba-products"])


def _read_service(session: AsyncSession) -> SambaProductService:
    return SambaProductService(SambaProductRepository(session))


def _write_service(session: AsyncSession) -> SambaProductService:
    return SambaProductService(SambaProductRepository(session))


@router.get("", response_model=list[SambaProduct])
async def list_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    status: Optional[str] = None,
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    # tenant_id가 있으면 해당 테넌트 + 기존(NULL) 상품 모두 조회
    if tenant_id:
        from sqlalchemy import or_

        stmt = select(SambaProduct).where(
            or_(
                SambaProduct.tenant_id == tenant_id,
                SambaProduct.tenant_id == None,  # noqa: E711
            )
        )
        if status:
            stmt = stmt.where(SambaProduct.status == status)
        stmt = stmt.offset(skip).limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()
    svc = _read_service(session)
    return await svc.list_products(skip=skip, limit=limit, status=status)


@router.get("/search", response_model=list[SambaProduct])
async def search_products(
    q: str = Query(..., min_length=1),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    # tenant_id가 있으면 해당 테넌트 상품만 검색
    if tenant_id:
        # q 는 외부 입력 — `%`/`_` 메타 escape 후 ESCAPE '\\' 명시.
        from backend.core.sql_safe import escape_like

        safe_q = f"%{escape_like(q)}%"
        stmt = (
            select(SambaProduct)
            .where(
                SambaProduct.tenant_id == tenant_id,
                SambaProduct.name.ilike(safe_q, escape="\\"),
            )
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.scalars().all()
    svc = _read_service(session)
    return await svc.search_products(q, limit)


@router.get("/{product_id}", response_model=SambaProduct)
async def get_product(
    product_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _read_service(session)
    product = await svc.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return product


@router.post("", response_model=SambaProduct, status_code=201)
async def create_product(
    body: ProductCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    svc = _write_service(session)
    data = body.model_dump(exclude_unset=True)
    # 테넌트 ID가 있으면 새 상품에 설정
    if tenant_id:
        data["tenant_id"] = tenant_id
    return await svc.create_product(data)


@router.put("/{product_id}", response_model=SambaProduct)
async def update_product(
    product_id: str,
    body: ProductUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    svc = _write_service(session)
    # 테넌트 소유권 검증: tenant_id가 있으면 해당 테넌트 상품만 수정 가능
    if tenant_id:
        existing = await svc.get_product(product_id)
        if not existing:
            raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
        if existing.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403, detail="해당 상품에 접근 권한이 없습니다"
            )
    product = await svc.update_product(product_id, body.model_dump(exclude_unset=True))
    if not product:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return product


@router.delete("/{product_id}")
async def delete_product(
    product_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    svc = _write_service(session)
    # 테넌트 소유권 검증: tenant_id가 있으면 해당 테넌트 상품만 삭제 가능
    if tenant_id:
        existing = await svc.get_product(product_id)
        if not existing:
            raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
        if existing.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403, detail="해당 상품에 접근 권한이 없습니다"
            )
    deleted = await svc.delete_product(product_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return {"ok": True}
