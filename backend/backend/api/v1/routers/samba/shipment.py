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


# ==================== 그룹상품 ====================


class GroupPreviewRequest(BaseModel):
  product_ids: list[str]
  account_id: str


class GroupPreviewProduct(BaseModel):
  id: str
  name: str
  color: Optional[str]
  sale_price: Optional[float]
  thumbnail: Optional[str]
  existing_product_no: Optional[str]


class GroupPreviewGroup(BaseModel):
  group_key: str
  group_name: str
  products: list[GroupPreviewProduct]


class GroupPreviewResponse(BaseModel):
  groups: list[GroupPreviewGroup]
  singles: list[GroupPreviewProduct]
  delete_count: int
  group_count: int
  single_count: int


@router.post("/group-preview")
async def group_preview(
  body: GroupPreviewRequest,
  session: AsyncSession = Depends(get_read_session_dependency),
):
  """전송 대상 상품에서 그룹핑 가능한 상품을 감지하여 미리보기 반환."""
  from collections import defaultdict

  from backend.domain.samba.collector.grouping import group_products_by_key
  from backend.domain.samba.collector.repository import SambaCollectedProductRepository

  repo = SambaCollectedProductRepository(session)
  products = []
  for pid in body.product_ids:
    p = await repo.get_async(pid)
    if p:
      products.append(p.model_dump())

  # search_filter_id별로 분리 후 그룹핑 (다른 검색그룹끼리는 묶지 않음)
  by_filter: dict[str, list[dict]] = defaultdict(list)
  for p in products:
    sf_id = p.get("search_filter_id") or "_none"
    by_filter[sf_id].append(p)

  all_groups: dict[str, list[dict]] = {}
  all_singles: list[dict] = []
  for sf_id, sf_products in by_filter.items():
    r = group_products_by_key(sf_products)
    all_groups.update(r["groups"])
    all_singles.extend(r["singles"])

  # 그룹별 미리보기 구성
  groups = []
  delete_count = 0
  for key, items in all_groups.items():
    first_name = items[0].get("name", "")
    group_name = (
      first_name.split(" - ", 1)[0].strip()
      if " - " in first_name
      else first_name
    )

    group_products = []
    for item in items:
      market_nos = item.get("market_product_nos") or {}
      existing_no = market_nos.get(body.account_id)
      if existing_no:
        if isinstance(existing_no, dict):
          existing_no = str(existing_no.get("originProductNo", ""))
        else:
          existing_no = str(existing_no)
        delete_count += 1
      else:
        existing_no = None
      item_images = item.get("images") or []
      group_products.append(GroupPreviewProduct(
        id=item["id"],
        name=item.get("name", ""),
        color=item.get("color"),
        sale_price=item.get("sale_price"),
        thumbnail=item_images[0] if item_images else None,
        existing_product_no=existing_no,
      ))
    groups.append(GroupPreviewGroup(
      group_key=key,
      group_name=group_name,
      products=group_products,
    ))

  singles = []
  for item in all_singles:
    item_images = item.get("images") or []
    market_nos = item.get("market_product_nos") or {}
    existing = market_nos.get(body.account_id)
    if existing and isinstance(existing, dict):
      existing = str(existing.get("originProductNo", ""))
    elif existing:
      existing = str(existing)
    else:
      existing = None
    singles.append(GroupPreviewProduct(
      id=item["id"],
      name=item.get("name", ""),
      color=item.get("color"),
      sale_price=item.get("sale_price"),
      thumbnail=item_images[0] if item_images else None,
      existing_product_no=existing,
    ))

  return GroupPreviewResponse(
    groups=groups,
    singles=singles,
    delete_count=delete_count,
    group_count=len(groups),
    single_count=len(singles),
  )


class GroupSendItem(BaseModel):
  group_key: str
  product_ids: list[str]


class GroupSendRequest(BaseModel):
  groups: list[GroupSendItem]
  singles: list[str]
  account_id: str


@router.post("/group-send")
async def group_send(
  body: GroupSendRequest,
  session: AsyncSession = Depends(get_write_session_dependency),
):
  """그룹상품 + 단일상품 전송."""
  svc = _get_service(session)
  results = []

  # 1. 그룹상품 전송
  for group in body.groups:
    try:
      result = await svc.transmit_group(
        product_ids=group.product_ids,
        account_id=body.account_id,
      )
      results.append({"group_key": group.group_key, "status": "success", **result})
    except Exception as e:
      results.append({"group_key": group.group_key, "status": "error", "error": str(e)})

  # 2. 단일상품 전송 (기존 방식)
  single_results = {}
  if body.singles:
    single_results = await svc.start_update(
      product_ids=body.singles,
      update_items=["price", "stock", "image", "description"],
      target_account_ids=[body.account_id],
    )

  return {
    "group_results": results,
    "single_results": single_results,
  }
