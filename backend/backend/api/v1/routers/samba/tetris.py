"""SambaWave Tetris 정책 배치 API router."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.tetris.repository import SambaTetrisRepository
from backend.domain.samba.tetris.service import SambaTetrisService
from backend.domain.samba.tenant.middleware import get_optional_tenant_id
from backend.dtos.samba.tetris import (
    TetrisAssignRequest,
    TetrisAssignResponse,
    TetrisBoardResponse,
    TetrisMoveRequest,
    TetrisReorderRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tetris", tags=["samba-tetris"])


def _get_service(session: AsyncSession) -> SambaTetrisService:
    """서비스 인스턴스 생성 헬퍼."""
    return SambaTetrisService(SambaTetrisRepository(session), session)


@router.get("/board", response_model=TetrisBoardResponse)
async def get_board(
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
) -> TetrisBoardResponse:
    """테트리스 보드 전체 구조 조회."""
    svc = _get_service(session)
    board = await svc.get_board(tenant_id)
    return TetrisBoardResponse(**board)


@router.post("/assign", response_model=TetrisAssignResponse, status_code=201)
async def assign_brand(
    body: TetrisAssignRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
) -> TetrisAssignResponse:
    """브랜드를 마켓 계정에 배치하고 상품 전송 트리거."""
    svc = _get_service(session)
    assignment = await svc.assign(
        tenant_id=tenant_id,
        source_site=body.source_site,
        brand_name=body.brand_name,
        market_account_id=body.market_account_id,
        policy_id=body.policy_id,
        position_order=body.position_order,
    )
    return TetrisAssignResponse(
        id=assignment.id,
        source_site=assignment.source_site,
        brand_name=assignment.brand_name,
        market_account_id=assignment.market_account_id,
        policy_id=assignment.policy_id,
        position_order=assignment.position_order,
    )


@router.delete("/assign/{assignment_id}", status_code=200)
async def remove_assignment(
    assignment_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
) -> dict[str, bool]:
    """배치 삭제 후 마켓 상품 삭제 트리거."""
    svc = _get_service(session)
    deleted = await svc.remove(assignment_id=assignment_id, tenant_id=tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="배치를 찾을 수 없습니다")
    return {"deleted": True}


@router.patch("/assign/{assignment_id}/move", response_model=TetrisAssignResponse)
async def move_assignment(
    assignment_id: str,
    body: TetrisMoveRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
) -> TetrisAssignResponse:
    """배치를 다른 계정으로 이동 — 기존 계정 마켓삭제 → 신규 계정 전송."""
    svc = _get_service(session)
    assignment = await svc.move(
        assignment_id=assignment_id,
        tenant_id=tenant_id,
        new_account_id=body.market_account_id,
        policy_id=body.policy_id,
        position_order=body.position_order,
    )
    return TetrisAssignResponse(
        id=assignment.id,
        source_site=assignment.source_site,
        brand_name=assignment.brand_name,
        market_account_id=assignment.market_account_id,
        policy_id=assignment.policy_id,
        position_order=assignment.position_order,
    )


@router.patch("/assign/{assignment_id}/reorder", response_model=TetrisAssignResponse)
async def reorder_assignment(
    assignment_id: str,
    body: TetrisReorderRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
) -> TetrisAssignResponse:
    """배치 순서만 변경 (shipment 트리거 없음)."""
    svc = _get_service(session)
    assignment = await svc.reorder(
        assignment_id=assignment_id,
        tenant_id=tenant_id,
        position_order=body.position_order,
    )
    return TetrisAssignResponse(
        id=assignment.id,
        source_site=assignment.source_site,
        brand_name=assignment.brand_name,
        market_account_id=assignment.market_account_id,
        policy_id=assignment.policy_id,
        position_order=assignment.position_order,
    )
