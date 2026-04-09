"""SambaWave Product API router."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.product.model import SambaProduct
from backend.domain.samba.product.repository import SambaProductRepository
from backend.domain.samba.product.service import SambaProductService
from backend.dtos.samba.product import ProductCreate, ProductUpdate

router = APIRouter(prefix="/products", tags=["samba-products"])


def _read_service(session: AsyncSession) -> SambaProductService:
    return SambaProductService(SambaProductRepository(session))


def _write_service(session: AsyncSession) -> SambaProductService:
    return SambaProductService(SambaProductRepository(session))


@router.get("", response_model=list[SambaProduct])
async def list_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = None,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _read_service(session)
    return await svc.list_products(skip=skip, limit=limit, status=status)


@router.get("/search", response_model=list[SambaProduct])
async def search_products(
    q: str = Query(..., min_length=1),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_read_session_dependency),
):
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
):
    svc = _write_service(session)
    return await svc.create_product(body.model_dump(exclude_unset=True))


@router.put("/{product_id}", response_model=SambaProduct)
async def update_product(
    product_id: str,
    body: ProductUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _write_service(session)
    product = await svc.update_product(product_id, body.model_dump(exclude_unset=True))
    if not product:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return product


@router.delete("/{product_id}")
async def delete_product(
    product_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _write_service(session)
    deleted = await svc.delete_product(product_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return {"ok": True}
