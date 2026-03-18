"""SambaWave Shipment service — 실제 마켓 API 연동 상품 전송."""

import asyncio
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.samba.shipment.model import SambaShipment
from backend.domain.samba.shipment.repository import SambaShipmentRepository
from backend.utils.logger import logger

STATUS_LABELS: Dict[str, str] = {
  "pending": "대기중",
  "updating": "업데이트중",
  "transmitting": "전송중",
  "completed": "완료",
  "partial": "부분완료",
  "failed": "실패",
}


class SambaShipmentService:
  def __init__(self, repo: SambaShipmentRepository, session: AsyncSession):
    self.repo = repo
    self.session = session

  # ==================== CRUD ====================

  async def list_shipments(
    self, skip: int = 0, limit: int = 50, status: Optional[str] = None
  ) -> List[SambaShipment]:
    if status:
      return await self.repo.list_by_status(status)
    return await self.repo.list_async(skip=skip, limit=limit, order_by="-created_at")

  async def list_by_status(self, status: str) -> List[SambaShipment]:
    return await self.repo.list_by_status(status)

  async def get_shipment(self, shipment_id: str) -> Optional[SambaShipment]:
    return await self.repo.get_async(shipment_id)

  async def create_shipment(self, data: Dict[str, Any]) -> SambaShipment:
    return await self.repo.create_async(**data)

  async def update_shipment(
    self, shipment_id: str, data: Dict[str, Any]
  ) -> Optional[SambaShipment]:
    return await self.repo.update_async(shipment_id, **data)

  async def delete_shipment(self, shipment_id: str) -> bool:
    return await self.repo.delete_async(shipment_id)

  async def list_by_product(self, product_id: str) -> List[SambaShipment]:
    return await self.repo.list_by_product(product_id)

  # ==================== 실제 상품 전송 ====================

  async def start_update(
    self,
    product_ids: List[str],
    update_items: List[str],
    target_account_ids: List[str],
    skip_unchanged: bool = False,
  ) -> int:
    """여러 상품을 대상 마켓 계정으로 실제 전송."""
    from backend.domain.samba.collector.repository import SambaCollectedProductRepository

    processed = 0
    skipped = 0
    product_repo = SambaCollectedProductRepository(self.session) if skip_unchanged else None
    for product_id in product_ids:
      try:
        # 스킵 로직: 가격 변동 없으면 건너뜀
        if skip_unchanged and product_repo:
          product = await product_repo.get_async(product_id)
          if product and product.price_history:
            history = product.price_history if isinstance(product.price_history, list) else []
            if len(history) >= 2:
              latest = history[0] if isinstance(history[0], dict) else {}
              prev = history[1] if isinstance(history[1], dict) else {}
              # 원가, 판매가 모두 동일하면 스킵
              if (latest.get("sale_price") == prev.get("sale_price")
                  and latest.get("cost") == prev.get("cost")):
                skipped += 1
                logger.info(f"스킵: {product_id} (가격 변동 없음)")
                continue

        await self._transmit_product(
          product_id, target_account_ids, update_items
        )
        processed += 1
      except Exception as exc:
        logger.error(f"상품 {product_id} 전송 실패: {exc}")

    if skipped > 0:
      logger.info(f"전송 완료: {processed}건 처리, {skipped}건 스킵")
    return processed

  async def _transmit_product(
    self,
    product_id: str,
    target_account_ids: List[str],
    update_items: List[str],
  ) -> SambaShipment:
    """단일 상품에 대한 실제 마켓 전송."""
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.account.repository import SambaMarketAccountRepository
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.collector.repository import SambaCollectedProductRepository
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market

    # 1. shipment 레코드 생성
    shipment = await self.repo.create_async(
      product_id=product_id,
      target_account_ids=target_account_ids,
      update_items=update_items,
      status="pending",
      update_result={},
      transmit_result={},
      transmit_error={},
    )

    # 2. 상품 데이터 조회
    product_repo = SambaCollectedProductRepository(self.session)
    product_row = await product_repo.get_async(product_id)
    if not product_row:
      await self.repo.update_async(
        shipment.id, status="failed", error="상품을 찾을 수 없습니다."
      )
      return shipment

    product_dict = product_row.model_dump()

    # 3. 카테고리 매핑 자동 조회
    mapped_categories = await self._resolve_category_mappings(
      product_row.source_site or "",
      product_row.category or "",
      target_account_ids,
    )
    await self.repo.update_async(shipment.id, mapped_categories=mapped_categories)

    # 4. 업데이트 단계
    await self.repo.update_async(shipment.id, status="updating")
    update_result: Dict[str, str] = {}
    for item in update_items:
      update_result[item] = "success"
    await self.repo.update_async(
      shipment.id, status="transmitting", update_result=update_result
    )

    # 5. 계정 정보 조회 및 마켓별 전송
    account_repo = SambaMarketAccountRepository(self.session)
    transmit_result: Dict[str, str] = {}
    transmit_error: Dict[str, str] = {}

    for account_id in target_account_ids:
      try:
        account = await account_repo.get_async(account_id)
        if not account:
          transmit_result[account_id] = "failed"
          transmit_error[account_id] = "계정을 찾을 수 없습니다."
          continue

        market_type = account.market_type
        # 카테고리 매핑에서 대상 카테고리 조회
        category_id = mapped_categories.get(market_type, "")

        # 실제 마켓 API 호출
        result = await dispatch_to_market(
          self.session, market_type, product_dict, category_id
        )

        if result.get("success"):
          transmit_result[account_id] = "success"
          logger.info(
            f"[전송] {market_type} 성공 - 상품: {product_id}, 계정: {account_id}"
          )
        else:
          transmit_result[account_id] = "failed"
          transmit_error[account_id] = result.get("message", "알 수 없는 오류")
          logger.warning(
            f"[전송] {market_type} 실패 - {result.get('message')}"
          )

      except Exception as exc:
        transmit_result[account_id] = "failed"
        transmit_error[account_id] = str(exc)
        logger.error(f"[전송] 계정 {account_id} 예외: {exc}")

    # 6. 최종 상태 결정
    values = list(transmit_result.values())
    all_success = len(values) > 0 and all(v == "success" for v in values)
    all_failed = len(values) > 0 and all(v == "failed" for v in values)

    if all_success:
      final_status = "completed"
    elif all_failed:
      final_status = "failed"
    else:
      final_status = "partial"

    updated = await self.repo.update_async(
      shipment.id,
      status=final_status,
      transmit_result=transmit_result,
      transmit_error=transmit_error if transmit_error else None,
      completed_at=datetime.now(UTC),
    )

    # 6. 상품 상태 업데이트 (등록된 계정 목록)
    success_accounts = [
      aid for aid, status in transmit_result.items() if status == "success"
    ]
    if success_accounts:
      existing = product_row.registered_accounts or []
      new_accounts = list(set(existing + success_accounts))
      await product_repo.update_async(
        product_id,
        registered_accounts=new_accounts,
        status="registered" if new_accounts else product_row.status,
      )

    logger.info(
      f"Shipment {shipment.id} 완료 status={final_status} "
      f"product={product_id} 성공={sum(1 for v in values if v == 'success')}/{len(values)}"
    )
    if not updated:
      logger.warning(f"Shipment {shipment.id} 업데이트 실패, DB 재조회")
      updated = await self.repo.get_async(shipment.id)
    return updated or shipment

  # ==================== 카테고리 매핑 자동 조회 ====================

  async def _resolve_category_mappings(
    self,
    source_site: str,
    source_category: str,
    target_account_ids: List[str],
  ) -> Dict[str, str]:
    """수집 상품의 소싱처 카테고리 → 각 마켓 카테고리 자동 매핑.

    1. DB에 저장된 매핑이 있으면 사용
    2. 없으면 키워드 기반 자동 제안으로 첫 번째 결과 사용
    """
    from backend.domain.samba.account.repository import SambaMarketAccountRepository
    from backend.domain.samba.category.repository import SambaCategoryMappingRepository
    from backend.domain.samba.category.service import SambaCategoryService

    if not source_category:
      return {}

    # DB에서 매핑 조회
    mapping_repo = SambaCategoryMappingRepository(self.session)
    mapping = await mapping_repo.find_mapping(source_site, source_category)

    result: Dict[str, str] = {}

    # 대상 계정의 마켓 타입 수집
    account_repo = SambaMarketAccountRepository(self.session)
    market_types = set()
    for aid in target_account_ids:
      acc = await account_repo.get_async(aid)
      if acc:
        market_types.add(acc.market_type)

    for market_type in market_types:
      # DB 매핑에 있으면 사용
      if mapping and mapping.target_mappings:
        target = mapping.target_mappings.get(market_type, "")
        if target:
          result[market_type] = target
          continue

      # 없으면 키워드 기반 자동 제안
      suggestions = SambaCategoryService.suggest_category(
        source_category, market_type
      )
      if suggestions:
        result[market_type] = suggestions[0]

    return result

  # ==================== 재전송 ====================

  async def retransmit(self, shipment_id: str) -> Optional[SambaShipment]:
    """실패한 계정에 대해 기존 shipment 레코드를 업데이트하며 재전송."""
    from backend.domain.samba.account.repository import SambaMarketAccountRepository
    from backend.domain.samba.collector.repository import SambaCollectedProductRepository
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market

    shipment = await self.repo.get_async(shipment_id)
    if not shipment:
      return None

    old_result = shipment.transmit_result or {}
    old_errors = shipment.transmit_error or {}
    failed_accounts = [
      aid for aid, st in old_result.items() if st == "failed"
    ]
    if not failed_accounts:
      return shipment

    # 상품 데이터 조회
    product_repo = SambaCollectedProductRepository(self.session)
    product_row = await product_repo.get_async(shipment.product_id)
    if not product_row:
      return shipment
    product_dict = product_row.model_dump()

    # 재전송
    await self.repo.update_async(shipment_id, status="transmitting")
    account_repo = SambaMarketAccountRepository(self.session)
    new_result = dict(old_result)
    new_errors = dict(old_errors)

    for account_id in failed_accounts:
      try:
        account = await account_repo.get_async(account_id)
        if not account:
          continue
        result = await dispatch_to_market(
          self.session, account.market_type, product_dict, ""
        )
        if result.get("success"):
          new_result[account_id] = "success"
          new_errors.pop(account_id, None)
        else:
          new_result[account_id] = "failed"
          new_errors[account_id] = result.get("message", "")
      except Exception as exc:
        new_result[account_id] = "failed"
        new_errors[account_id] = str(exc)

    values = list(new_result.values())
    all_success = len(values) > 0 and all(v == "success" for v in values)
    all_failed = len(values) > 0 and all(v == "failed" for v in values)
    final_status = "completed" if all_success else ("failed" if all_failed else "partial")

    updated = await self.repo.update_async(
      shipment_id,
      status=final_status,
      transmit_result=new_result,
      transmit_error=new_errors if new_errors else None,
      completed_at=datetime.now(UTC),
    )
    return updated or shipment

  @staticmethod
  def get_status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)
