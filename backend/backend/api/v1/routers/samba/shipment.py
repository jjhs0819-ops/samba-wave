"""SambaWave Shipment API router."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency

router = APIRouter(prefix="/shipments", tags=["samba-shipments"])


class ShipmentStartRequest(BaseModel):
  product_ids: list[str]
  update_items: list[str]  # ['price', 'stock', 'image', 'description']
  target_account_ids: list[str]
  skip_unchanged: bool = False  # 가격 변동 없으면 스킵


class MarketDeleteRequest(BaseModel):
  product_ids: list[str]
  target_account_ids: list[str]


def _get_service(session: AsyncSession):
  from backend.domain.samba.shipment.repository import SambaShipmentRepository
  from backend.domain.samba.shipment.service import SambaShipmentService

  return SambaShipmentService(SambaShipmentRepository(session), session)


@router.get("")
async def list_shipments(
  skip: int = Query(0, ge=0),
  limit: int = Query(50, ge=1, le=200),
  status: Optional[str] = None,
  session: AsyncSession = Depends(get_read_session_dependency),
):
  svc = _get_service(session)
  return await svc.list_shipments(skip=skip, limit=limit, status=status)


@router.get("/product/{product_id}")
async def list_by_product(
  product_id: str,
  session: AsyncSession = Depends(get_read_session_dependency),
):
  return await _get_service(session).list_by_product(product_id)


@router.get("/{shipment_id}")
async def get_shipment(
  shipment_id: str,
  session: AsyncSession = Depends(get_read_session_dependency),
):
  svc = _get_service(session)
  s = await svc.get_shipment(shipment_id)
  if not s:
    raise HTTPException(404, "전송 기록을 찾을 수 없습니다")
  return s


@router.post("/start", status_code=201)
async def start_shipment(
  body: ShipmentStartRequest,
  session: AsyncSession = Depends(get_write_session_dependency),
):
  svc = _get_service(session)
  result = await svc.start_update(
    body.product_ids, body.update_items, body.target_account_ids,
    skip_unchanged=body.skip_unchanged,
  )
  return result


@router.post("/market-delete")
async def market_delete(
  body: MarketDeleteRequest,
  session: AsyncSession = Depends(get_write_session_dependency),
):
  """선택된 상품을 대상 마켓에서 판매중지/삭제."""
  svc = _get_service(session)
  return await svc.delete_from_markets(
    body.product_ids, body.target_account_ids
  )


@router.post("/{shipment_id}/retry")
async def retry_shipment(
  shipment_id: str,
  session: AsyncSession = Depends(get_write_session_dependency),
):
  svc = _get_service(session)
  result = await svc.retransmit(shipment_id)
  if not result:
    raise HTTPException(404, "전송 기록을 찾을 수 없습니다")
  return result
