"""SambaWave Policy API router."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.policy.model import SambaPolicy
from backend.domain.samba.policy.repository import SambaPolicyRepository
from backend.domain.samba.policy.service import SambaPolicyService
from backend.dtos.samba.policy import PolicyCreate, PolicyUpdate, PriceCalculateRequest

router = APIRouter(prefix="/policies", tags=["samba-policies"])


def _read_service(session: AsyncSession) -> SambaPolicyService:
    return SambaPolicyService(SambaPolicyRepository(session))


def _write_service(session: AsyncSession) -> SambaPolicyService:
    return SambaPolicyService(SambaPolicyRepository(session))


@router.get("", response_model=list[SambaPolicy])
async def list_policies(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _read_service(session)
    return await svc.list_policies(skip=skip, limit=limit)


@router.get("/{policy_id}", response_model=SambaPolicy)
async def get_policy(
    policy_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _read_service(session)
    policy = await svc.get_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="정책을 찾을 수 없습니다")
    return policy


@router.post("", response_model=SambaPolicy, status_code=201)
async def create_policy(
    body: PolicyCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _write_service(session)
    return await svc.create_policy(body.model_dump(exclude_unset=True))


@router.put("/{policy_id}", response_model=SambaPolicy)
async def update_policy(
    policy_id: str,
    body: PolicyUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _write_service(session)
    policy = await svc.update_policy(policy_id, body.model_dump(exclude_unset=True))
    if not policy:
        raise HTTPException(status_code=404, detail="정책을 찾을 수 없습니다")
    return policy


@router.delete("/{policy_id}")
async def delete_policy(
    policy_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _write_service(session)
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
    svc = _read_service(session)
    return await svc.get_price_preview(policy_id, body.cost, body.fee_rate)
