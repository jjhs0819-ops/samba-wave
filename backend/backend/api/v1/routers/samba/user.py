"""삼바웨이브 사용자(로그인 계정) 관리 API."""

import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.user.model import SambaUser
from backend.domain.samba.user.repository import SambaUserRepository
from backend.domain.user.auth_service import get_user_id
from backend.utils.logger import logger
from backend.utils.password import hash_password, verify_password

router = APIRouter(prefix="/users", tags=["samba-users"])


# ── DTO ──

INVITE_CODE = os.environ.get("SAMBA_INVITE_CODE", "samba_wave")


class UserCreateDto(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    name: str = Field(..., min_length=1, max_length=50)
    invite_code: str = Field("", description="초대 코드")


class UserLoginDto(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class UserUpdateDto(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=6)
    status: Optional[str] = None


class UserOut(BaseModel):
    id: str
    email: Optional[str] = None
    name: Optional[str] = None
    is_admin: bool = False
    status: str = "active"
    created_at: str
    updated_at: str
    access_token: Optional[str] = None


# ── 엔드포인트 ──


@router.get("", response_model=list[UserOut])
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_read_session_dependency),
    _user_id: str = Depends(get_user_id),
):
    """활성 사용자 목록 조회 (삭제된 사용자 제외)."""
    stmt = (
        select(SambaUser)
        .where(SambaUser.deleted_at.is_(None))
        .order_by(SambaUser.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(stmt)
    users = result.scalars().all()
    return [
        UserOut(
            id=u.id,
            email=u.email,
            name=u.name,
            is_admin=u.is_admin,
            status=u.status,
            created_at=u.created_at.isoformat(),
            updated_at=u.updated_at.isoformat(),
        )
        for u in users
    ]


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreateDto,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """새 사용자 계정 생성."""
    # 초대 코드 검증
    if body.invite_code != INVITE_CODE:
        raise HTTPException(status_code=403, detail="초대 코드가 올바르지 않습니다")

    repo = SambaUserRepository(session)

    # 이메일 중복 검사
    existing = await repo.find_by_email(body.email)
    if existing:
        raise HTTPException(status_code=409, detail="이미 등록된 이메일입니다")

    hashed = hash_password(body.password)
    user = await repo.create_async(
        email=body.email,
        name=body.name,
        password_hash=hashed,
        is_admin=False,
        status="active",
    )
    logger.info(f"[사용자관리] 계정 생성: {user.email}")

    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        is_admin=user.is_admin,
        status=user.status,
        created_at=user.created_at.isoformat(),
        updated_at=user.updated_at.isoformat(),
    )


@router.post("/login", response_model=UserOut)
async def login_user(
    body: UserLoginDto,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """이메일/비밀번호 로그인."""
    repo = SambaUserRepository(session)
    user = await repo.find_by_email(body.email)
    if not user:
        raise HTTPException(
            status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다"
        )

    if user.status != "active":
        raise HTTPException(status_code=403, detail="비활성 계정입니다")

    if not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다"
        )

    # JWT 토큰 발급
    from backend.domain.user.auth_service import AuthService

    auth_svc = AuthService(session)
    access_token = auth_svc._create_access_token(user.id)

    logger.info(f"[사용자관리] 로그인: {user.email}")
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        is_admin=user.is_admin,
        status=user.status,
        created_at=user.created_at.isoformat(),
        updated_at=user.updated_at.isoformat(),
        access_token=access_token,
    )


@router.put("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    body: UserUpdateDto,
    session: AsyncSession = Depends(get_write_session_dependency),
    _user_id: str = Depends(get_user_id),
):
    """사용자 정보 수정."""
    repo = SambaUserRepository(session)
    user = await repo.get_async(user_id)
    if not user or user.deleted_at is not None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    update_data: dict[str, Any] = {}
    if body.name is not None:
        update_data["name"] = body.name
    if body.email is not None:
        # 이메일 변경 시 중복 검사
        if body.email != user.email:
            dup = await repo.find_by_email(body.email)
            if dup:
                raise HTTPException(status_code=409, detail="이미 등록된 이메일입니다")
        update_data["email"] = body.email
    if body.password is not None:
        update_data["password_hash"] = hash_password(body.password)
    if body.status is not None:
        update_data["status"] = body.status

    if update_data:
        updated = await repo.update_async(user_id, **update_data)
        if updated:
            user = updated

    logger.info(f"[사용자관리] 계정 수정: {user.email}")

    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        is_admin=user.is_admin,
        status=user.status,
        created_at=user.created_at.isoformat(),
        updated_at=user.updated_at.isoformat(),
    )


@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
    _user_id: str = Depends(get_user_id),
):
    """사용자 계정 삭제 (소프트 삭제)."""
    repo = SambaUserRepository(session)
    success = await repo.soft_delete(user_id)
    if not success:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
    logger.info(f"[사용자관리] 계정 삭제: {user_id}")
    return {"ok": True}
