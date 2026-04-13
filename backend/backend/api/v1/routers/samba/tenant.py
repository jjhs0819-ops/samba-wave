"""테넌트 관리 API — 관리자 전용 + 사용량 조회."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.tenant.middleware import (
    get_optional_tenant_id,
    require_admin,
)
from backend.domain.samba.tenant.repository import SambaTenantRepository
from backend.domain.samba.tenant.service import SambaTenantService

router = APIRouter(prefix="/tenants", tags=["samba-tenants"])


class TenantCreate(BaseModel):
    name: str
    owner_user_id: str = ""
    plan: str = "free"


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    plan: Optional[str] = None
    limits: Optional[dict] = None
    is_active: Optional[bool] = None
    autotune_enabled: Optional[bool] = None


@router.get("")
async def list_tenants(
    skip: int = 0,
    limit: int = 50,
    session: AsyncSession = Depends(get_read_session_dependency),
    _admin_id: str = Depends(require_admin),
):
    svc = SambaTenantService(SambaTenantRepository(session))
    return await svc.list_tenants(skip=skip, limit=limit)


@router.post("", status_code=201)
async def create_tenant(
    body: TenantCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
    _admin_id: str = Depends(require_admin),
):
    svc = SambaTenantService(SambaTenantRepository(session))
    tenant = await svc.create_tenant(body.model_dump())
    await session.commit()
    return tenant


# ── 사용자용 (/me/* 는 /{tenant_id} 보다 먼저 선언해야 함) ──


@router.get("/me/info")
async def get_my_tenant(
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    """내 테넌트 정보 조회."""
    if not tenant_id:
        return {"tenant": None}

    repo = SambaTenantRepository(session)
    tenant = await repo.get_async(tenant_id)
    if not tenant:
        return {"tenant": None}

    return {
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "plan": tenant.plan,
            "limits": tenant.limits,
            "autotune_enabled": tenant.autotune_enabled,
            "subscription_start": tenant.subscription_start,
            "subscription_end": tenant.subscription_end,
            "is_active": tenant.is_active,
        }
    }


@router.get("/me/usage")
async def get_my_usage(
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    """내 테넌트 사용량 vs 제한 조회."""
    if not tenant_id:
        return {"usage": None}

    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.sourcing_account.model import SambaSourcingAccount

    repo = SambaTenantRepository(session)
    tenant = await repo.get_async(tenant_id)
    if not tenant:
        return {"usage": None}

    limits = tenant.limits or {
        "max_products": 1000,
        "max_markets": 3,
        "max_sourcing": 2,
    }

    # 현재 사용량 조회
    product_count = (
        await session.execute(
            select(func.count())
            .select_from(SambaCollectedProduct)
            .where(SambaCollectedProduct.tenant_id == tenant_id)
        )
    ).scalar() or 0

    market_count = (
        await session.execute(
            select(func.count())
            .select_from(SambaMarketAccount)
            .where(SambaMarketAccount.tenant_id == tenant_id)
        )
    ).scalar() or 0

    sourcing_count = (
        await session.execute(
            select(func.count())
            .select_from(SambaSourcingAccount)
            .where(SambaSourcingAccount.tenant_id == tenant_id)
        )
    ).scalar() or 0

    return {
        "plan": tenant.plan,
        "autotune_enabled": tenant.autotune_enabled,
        "subscription_end": tenant.subscription_end,
        "usage": {
            "products": {
                "current": product_count,
                "max": limits.get("max_products", 1000),
            },
            "markets": {"current": market_count, "max": limits.get("max_markets", 3)},
            "sourcing": {
                "current": sourcing_count,
                "max": limits.get("max_sourcing", 2),
            },
        },
    }


# ── 관리자용 (/{tenant_id} 패턴 — /me/* 보다 뒤에 선언) ──


@router.get("/{tenant_id}")
async def get_tenant(
    tenant_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
    _admin_id: str = Depends(require_admin),
):
    svc = SambaTenantService(SambaTenantRepository(session))
    tenant = await svc.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(404, "테넌트를 찾을 수 없습니다")
    return tenant


@router.put("/{tenant_id}")
async def update_tenant(
    tenant_id: str,
    body: TenantUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
    _admin_id: str = Depends(require_admin),
):
    svc = SambaTenantService(SambaTenantRepository(session))
    data = body.model_dump(exclude_unset=True)
    result = await svc.update_tenant(tenant_id, data)
    await session.commit()
    return result
