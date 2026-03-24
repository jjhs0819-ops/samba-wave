"""테넌트 미들웨어 — JWT에서 tenant_id 추출 + 플랜 제한 체크."""

import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency

logger = logging.getLogger(__name__)


async def get_current_tenant_id(
    request: Request,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> str:
    """JWT → user → tenant_id 추출. 인증 필수 API에 사용."""
    # Authorization 헤더에서 JWT 토큰 추출
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "인증 토큰이 없습니다")

    token = auth_header.split(" ", 1)[1]
    try:
        from backend.core.config import settings
        import jwt
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        user_id = payload.get("sub", "")
    except Exception:
        raise HTTPException(401, "유효하지 않은 토큰입니다")

    if not user_id:
        raise HTTPException(401, "사용자 정보를 찾을 수 없습니다")

    # DB에서 user의 tenant_id 조회
    from backend.domain.samba.user.model import SambaUser
    from sqlmodel import select
    stmt = select(SambaUser).where(SambaUser.id == user_id)
    result = await session.execute(stmt)
    user = result.scalars().first()
    if not user:
        raise HTTPException(401, "사용자를 찾을 수 없습니다")

    tenant_id = getattr(user, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(403, "테넌트가 설정되지 않았습니다. 관리자에게 문의하세요.")

    return tenant_id


async def get_optional_tenant_id(
    request: Request,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> Optional[str]:
    """테넌트 ID 선택적 추출 — 인증 없어도 동작하는 API용 (과도기)."""
    try:
        return await get_current_tenant_id(request, session)
    except HTTPException:
        return None
    except Exception:
        return None


async def check_product_limit(tenant_id: str, session: AsyncSession):
    """상품 생성 전 플랜 제한 체크."""
    from backend.domain.samba.tenant.repository import SambaTenantRepository
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from sqlalchemy import func
    from sqlmodel import select

    tenant_repo = SambaTenantRepository(session)
    tenant = await tenant_repo.get_async(tenant_id)
    if not tenant:
        raise HTTPException(403, "테넌트를 찾을 수 없습니다")

    max_products = (tenant.limits or {}).get("max_products", 1000)
    count_stmt = select(func.count()).select_from(SambaCollectedProduct).where(
        SambaCollectedProduct.tenant_id == tenant_id
    )
    current = (await session.execute(count_stmt)).scalar() or 0

    if current >= max_products:
        raise HTTPException(
            403,
            f"상품 수 제한 초과 ({current}/{max_products}). 플랜을 업그레이드해주세요."
        )


async def check_market_limit(tenant_id: str, session: AsyncSession):
    """마켓 계정 생성 전 플랜 제한 체크."""
    from backend.domain.samba.tenant.repository import SambaTenantRepository
    from backend.domain.samba.account.model import SambaMarketAccount
    from sqlalchemy import func
    from sqlmodel import select

    tenant_repo = SambaTenantRepository(session)
    tenant = await tenant_repo.get_async(tenant_id)
    if not tenant:
        raise HTTPException(403, "테넌트를 찾을 수 없습니다")

    max_markets = (tenant.limits or {}).get("max_markets", 3)
    count_stmt = select(func.count()).select_from(SambaMarketAccount).where(
        SambaMarketAccount.tenant_id == tenant_id
    )
    current = (await session.execute(count_stmt)).scalar() or 0

    if current >= max_markets:
        raise HTTPException(
            403,
            f"마켓 계정 수 제한 초과 ({current}/{max_markets}). 플랜을 업그레이드해주세요."
        )
