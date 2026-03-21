"""SambaWave Shipment service — 실제 마켓 API 연동 상품 전송."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.samba.shipment.model import SambaShipment
from backend.domain.samba.shipment.repository import SambaShipmentRepository
from backend.utils.logger import logger

STATUS_LABELS: dict[str, str] = {
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
  ) -> list[SambaShipment]:
    if status:
      return await self.repo.list_by_status(status)
    return await self.repo.list_async(skip=skip, limit=limit, order_by="-created_at")

  async def list_by_status(self, status: str) -> list[SambaShipment]:
    return await self.repo.list_by_status(status)

  async def get_shipment(self, shipment_id: str) -> Optional[SambaShipment]:
    return await self.repo.get_async(shipment_id)

  async def create_shipment(self, data: dict[str, Any]) -> SambaShipment:
    return await self.repo.create_async(**data)

  async def update_shipment(
    self, shipment_id: str, data: dict[str, Any]
  ) -> Optional[SambaShipment]:
    return await self.repo.update_async(shipment_id, **data)

  async def delete_shipment(self, shipment_id: str) -> bool:
    return await self.repo.delete_async(shipment_id)

  async def list_by_product(self, product_id: str) -> list[SambaShipment]:
    return await self.repo.list_by_product(product_id)

  # ==================== 실제 상품 전송 ====================

  async def start_update(
    self,
    product_ids: list[str],
    update_items: list[str],
    target_account_ids: list[str],
    skip_unchanged: bool = False,
  ) -> dict[str, Any]:
    """여러 상품을 대상 마켓 계정으로 실제 전송. 마켓별 결과 반환."""
    from backend.domain.samba.collector.repository import SambaCollectedProductRepository

    processed = 0
    skipped = 0
    results: list[dict[str, Any]] = []
    product_repo = SambaCollectedProductRepository(self.session) if skip_unchanged else None
    for product_id in product_ids:
      try:
        if skip_unchanged and product_repo:
          product = await product_repo.get_async(product_id)
          if product and product.price_history:
            history = product.price_history if isinstance(product.price_history, list) else []
            if len(history) >= 2:
              latest = history[0] if isinstance(history[0], dict) else {}
              prev = history[1] if isinstance(history[1], dict) else {}
              if (latest.get("sale_price") == prev.get("sale_price")
                  and latest.get("cost") == prev.get("cost")):
                skipped += 1
                results.append({"product_id": product_id, "status": "skipped"})
                continue

        shipment = await self._transmit_product(
          product_id, target_account_ids, update_items
        )
        results.append({
          "product_id": product_id,
          "status": shipment.status,
          "transmit_result": shipment.transmit_result or {},
          "transmit_error": shipment.transmit_error or {},
        })
        processed += 1
      except Exception as exc:
        logger.error(f"상품 {product_id} 전송 실패: {exc}")
        results.append({
          "product_id": product_id,
          "status": "failed",
          "error": str(exc),
        })

    return {"processed": processed, "skipped": skipped, "results": results}

  async def _transmit_product(
    self,
    product_id: str,
    target_account_ids: list[str],
    update_items: list[str],
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

    # 2-1. 정책의 상세 템플릿으로 detail_html 항상 재생성
    # (수집된 detail_html은 소싱처 CDN URL이 포함되어 있어 마켓에서 핫링크 차단됨)
    product_dict["detail_html"] = await self._build_detail_html(product_dict)

    # 3. 카테고리 매핑 자동 조회 (성별 + category1~4 조합)
    cat_parts = [
      product_row.category1, product_row.category2,
      product_row.category3, product_row.category4,
    ]
    raw_category = " > ".join(c for c in cat_parts if c) or product_row.category or ""

    # 성별 prefix는 의류 카테고리일 때만 추가 (신발/가방 등은 제외)
    sex_prefix = ""
    cat1 = (product_row.category1 or "").strip()
    clothing_categories = {"상의", "하의", "아우터", "원피스", "니트", "셔츠", "팬츠", "의류"}
    if cat1 in clothing_categories:
      kream = product_row.kream_data if hasattr(product_row, "kream_data") else None
      if isinstance(kream, dict):
        sex_list = kream.get("sex", [])
        if isinstance(sex_list, list) and sex_list:
          sex = sex_list[0]
          if "남" in sex:
            sex_prefix = "남성의류"
          elif "여" in sex:
            sex_prefix = "여성의류"

    source_category = f"{sex_prefix} > {raw_category}" if sex_prefix and raw_category else raw_category
    mapped_categories = await self._resolve_category_mappings(
      product_row.source_site or "",
      source_category,
      target_account_ids,
    )
    # 성별 prefix 포함 시 매핑 못 찾으면 prefix 없이 재시도
    if sex_prefix and not mapped_categories:
      mapped_categories = await self._resolve_category_mappings(
        product_row.source_site or "",
        raw_category,
        target_account_ids,
      )
    await self.repo.update_async(shipment.id, mapped_categories=mapped_categories)

    # 4. 업데이트 단계
    await self.repo.update_async(shipment.id, status="updating")
    update_result: dict[str, str] = {}
    for item in update_items:
      update_result[item] = "success"
    await self.repo.update_async(
      shipment.id, status="transmitting", update_result=update_result
    )

    # 5. 계정 정보 조회 및 마켓별 전송
    account_repo = SambaMarketAccountRepository(self.session)

    # 정책 기반 계정 필터링: 정책이 있으면 참조하되, 사용자 선택 계정은 보존
    policy = None
    policy_market_data: dict[str, Any] = {}
    MARKET_TYPE_TO_POLICY_KEY = {
      'coupang': '쿠팡', 'ssg': '신세계몰', 'smartstore': '스마트스토어',
      '11st': '11번가', 'gmarket': '지마켓', 'auction': '옥션',
      'gsshop': 'GS샵', 'lotteon': '롯데ON', 'lottehome': '롯데홈쇼핑',
      'homeand': '홈앤쇼핑', 'hmall': 'HMALL', 'kream': 'KREAM',
      'ebay': 'eBay', 'lazada': 'Lazada', 'qoo10': 'Qoo10',
      'shopee': 'Shopee', 'shopify': 'Shopify', 'zoom': 'Zum(줌)',
    }
    if not product_row.applied_policy_id:
      logger.warning(f"[전송] 상품 {product_id} 정책 미설정 — 전송 차단")
      await self.repo.update_async(
        shipment.id, status="failed", error="정책 미적용 상품은 전송할 수 없습니다."
      )
      return shipment

    from backend.domain.samba.policy.repository import SambaPolicyRepository
    policy_repo = SambaPolicyRepository(self.session)
    policy = await policy_repo.get_async(product_row.applied_policy_id)
    if policy and policy.market_policies:
      policy_market_data = policy.market_policies

    # 정책의 상품명 규칙(name_rule) 기반 상품명 조합 적용
    if policy and policy.extras:
      name_rule_id = (policy.extras or {}).get("name_rule_id")
      if name_rule_id:
        from backend.domain.samba.policy.model import SambaNameRule
        from sqlmodel import select
        stmt = select(SambaNameRule).where(SambaNameRule.id == name_rule_id)
        result = await self.session.exec(stmt)
        name_rule = result.first()
        if name_rule:
          product_dict["name"] = self._compose_product_name(product_dict, name_rule)

    # 글로벌 삭제어 적용 (상품명에서 금칙어 제거)
    # DB 실제 데이터: type='deletion', scope='all'
    import re as _re
    from backend.domain.samba.forbidden.repository import SambaForbiddenWordRepository
    fw_repo = SambaForbiddenWordRepository(self.session)
    forbidden_words = await fw_repo.list_active("deletion")
    if forbidden_words and product_dict.get("name"):
      name = product_dict["name"]
      for fw in forbidden_words:
        if fw.word:
          name = _re.sub(_re.escape(fw.word), "", name, flags=_re.IGNORECASE)
      # 연속 공백 정리
      product_dict["name"] = _re.sub(r"\s{2,}", " ", name).strip()

    # 정책이 있으면 계정 필터링, 없으면 사용자 선택 전체 유지
    if policy_market_data:
      filtered_ids = []
      for aid in target_account_ids:
        acc = await account_repo.get_async(aid)
        if not acc:
          continue
        policy_key = MARKET_TYPE_TO_POLICY_KEY.get(acc.market_type)
        if not policy_key:
          # 정책 키 매핑 안 되는 마켓 → 그대로 허용
          filtered_ids.append(aid)
          continue
        mp = policy_market_data.get(policy_key, {})
        if not mp:
          # 정책에 이 마켓이 없음 → 그대로 허용 (사용자가 직접 선택)
          filtered_ids.append(aid)
          continue
        policy_acc_ids = mp.get("accountIds", [])
        if not policy_acc_ids and mp.get("accountId"):
          policy_acc_ids = [mp["accountId"]]
        # 정책에 계정 목록이 있으면 해당 계정만, 없으면 모두 허용
        if policy_acc_ids and aid not in policy_acc_ids:
          continue
        filtered_ids.append(aid)
      target_account_ids = filtered_ids
      logger.info(
        f"[전송] 정책 필터링 후 계정: {len(target_account_ids)}개"
      )

    transmit_result: dict[str, str] = {}
    transmit_error: dict[str, str] = {}

    for account_id in target_account_ids:
      try:
        account = await account_repo.get_async(account_id)
        if not account:
          transmit_result[account_id] = "failed"
          transmit_error[account_id] = "계정을 찾을 수 없습니다."
          continue

        market_type = account.market_type
        category_id = mapped_categories.get(market_type, "")

        # 카테고리 매핑 없으면 해당 마켓 전송 차단
        if not category_id:
          transmit_result[account_id] = "failed"
          transmit_error[account_id] = "카테고리 매핑 없음"
          logger.warning(f"[전송] 상품 {product_id} → {market_type} 카테고리 매핑 없음 (스킵)")
          continue

        # 최하단 카테고리(leaf) 코드 검증 — 숫자 코드가 아니면 leaf 미매핑
        # 쿠팡은 디스패처에서 경로→코드 동적 변환하므로 제외
        if market_type != "coupang" and not str(category_id).isdigit():
          transmit_result[account_id] = "failed"
          transmit_error[account_id] = f"최하단 카테고리 매핑 필요 (현재: {category_id})"
          logger.warning(
            f"[전송] 상품 {product_id} → {market_type} 최하단 카테고리 미매핑: '{category_id}' (스킵)"
          )
          continue

        # 정책 기반 판매가 계산 (프론트 products/page.tsx 계산 로직 동일)
        import math
        cost = product_dict.get("cost") or product_dict.get("sale_price") or product_dict.get("original_price") or 0
        if policy and policy.pricing:
          pr = policy.pricing
          common_margin_rate = pr.get("marginRate", 15)
          common_shipping = pr.get("shippingCost", 0)
          common_extra = pr.get("extraCharge", 0)
          common_fee = pr.get("feeRate", 0)
          min_margin = pr.get("minMarginAmount", 0)

          # 마켓별 개별 설정 (0이면 공통값 사용 — 프론트 로직 동일)
          policy_key = MARKET_TYPE_TO_POLICY_KEY.get(market_type)
          mp = policy_market_data.get(policy_key, {}) if policy_key else {}
          m_margin_rate = mp.get("marginRate") or common_margin_rate
          m_shipping = mp.get("shippingCost") or common_shipping
          m_fee = mp.get("feeRate") or common_fee

          margin_amt = round(cost * m_margin_rate / 100)
          if min_margin > 0 and margin_amt < min_margin:
            margin_amt = min_margin
          calc_price = cost + margin_amt + m_shipping
          if m_fee > 0 and calc_price > 0:
            calc_price = math.ceil(calc_price / (1 - m_fee / 100))
          if common_extra > 0:
            calc_price += common_extra

          product_dict["sale_price"] = calc_price
          logger.info(f"[전송] 정책 가격 계산: 원가={cost}, 마진={margin_amt}({m_margin_rate}%), 배송={m_shipping}, 수수료={m_fee}% → 판매가={calc_price}")

        # 기존 마켓 상품번호 확인 (있으면 수정, 없으면 신규등록)
        existing_nos = product_row.market_product_nos or {}
        if market_type == "smartstore":
          existing_product_no = existing_nos.get(f"{account_id}_origin", "") or existing_nos.get(account_id, "")
        else:
          existing_product_no = existing_nos.get(account_id, "")
        if existing_product_no:
          logger.info(f"[전송] 기존 상품번호 발견 → 수정 모드: {market_type} #{existing_product_no}")

        # 실제 마켓 API 호출 (계정 정보 직접 전달)
        result = await dispatch_to_market(
          self.session, market_type, product_dict, category_id,
          account=account,
          existing_product_no=existing_product_no,
        )

        if result.get("success"):
          transmit_result[account_id] = "success"
          # 404 신규 전환 시 이전 상품번호 DB에서 제거
          if "신규 전환" in (result.get("message") or ""):
            old_nos = product_row.market_product_nos or {}
            for key in [account_id, f"{account_id}_origin"]:
              old_nos.pop(key, None)
            await product_repo.update_async(product_id, market_product_nos=old_nos or None)
            logger.info(f"[전송] 404 전환 — 이전 상품번호 제거: {account_id}")
          # 마켓 상품번호 추출 (API 응답에서)
          # 롯데ON은 핸들러가 result에 spdNo를 직접 포함
          product_no = result.get("spdNo") or ""
          if not product_no:
            result_data = result.get("data", {})
            if isinstance(result_data, dict):
              api_data = result_data.get("data", result_data)
              # api_data가 리스트인 경우 (롯데ON 등) 첫번째 항목에서 추출
              if isinstance(api_data, list) and api_data:
                api_data = api_data[0] if isinstance(api_data[0], dict) else {}
              if isinstance(api_data, dict):
                # 마켓별 상품번호 키 추출
                # 스마트스토어: 구매페이지 URL용 channelProductNo 우선 저장
                product_no = (
                  api_data.get("smartstoreChannelProductNo")  # 스마트스토어 (구매페이지 URL용)
                  or api_data.get("originProductNo")       # 스마트스토어 (API용)
                  or api_data.get("productNo")             # 11번가
                  or api_data.get("sellerProductId")     # 쿠팡
                  or api_data.get("spdNo")               # 롯데ON
                  or api_data.get("itemId")              # SSG(신세계몰)
                  or api_data.get("supPrdCd")            # GS샵
                  or api_data.get("prdNo")               # GS샵 대체
                  or api_data.get("goodsNo")             # 롯데홈쇼핑
                  or api_data.get("product_id")
                  or api_data.get("productId")
                  or ""
                )
          if product_no:
            existing_nos = product_row.market_product_nos or {}
            existing_nos[account_id] = str(product_no)
            # 스마트스토어: originProductNo도 별도 저장 (수정/삭제 API용)
            if market_type == "smartstore" and isinstance(api_data, dict):
              origin_no = api_data.get("originProductNo") or ""
              if origin_no:
                existing_nos[f"{account_id}_origin"] = str(origin_no)
            await product_repo.update_async(
              product_id, market_product_nos=existing_nos
            )
            logger.info(f"[전송] {market_type} 상품번호 저장: {product_no}")
          action = "수정" if existing_product_no else "등록"
          logger.info(
            f"[전송] {market_type} {action} 성공 - 상품: {product_id}, 계정: {account_id}"
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
    # 성공한 계정은 추가, 실패한 계정은 제거
    success_accounts = [
      aid for aid, status in transmit_result.items() if status == "success"
    ]
    failed_accounts = [
      aid for aid, status in transmit_result.items() if status != "success"
    ]
    existing = product_row.registered_accounts or []
    existing_nos = product_row.market_product_nos or {}
    # 성공 추가 + 실패 제거
    new_accounts = list(set(
      [a for a in existing if a not in failed_accounts] + success_accounts
    ))
    # 실패한 계정의 상품번호도 제거
    new_nos = {k: v for k, v in existing_nos.items() if k not in failed_accounts}
    # 성공한 계정의 상품번호 유지 (transmit_result에서 product_no 추출 안 하므로 기존 값 보존)
    update_data: dict[str, Any] = {
      "registered_accounts": new_accounts if new_accounts else None,
      "market_product_nos": new_nos if new_nos else None,
      "status": "registered" if new_accounts else "collected",
    }
    await product_repo.update_async(product_id, **update_data)

    logger.info(
      f"Shipment {shipment.id} 완료 status={final_status} "
      f"product={product_id} 성공={sum(1 for v in values if v == 'success')}/{len(values)}"
    )
    if not updated:
      logger.warning(f"Shipment {shipment.id} 업데이트 실패, DB 재조회")
      updated = await self.repo.get_async(shipment.id)
    return updated or shipment

  # ==================== 상품명 조합 ====================

  def _compose_product_name(self, product: dict[str, Any], name_rule: Any) -> str:
    """정책의 상품명 규칙(name_composition)에 따라 상품명을 조합."""
    composition = name_rule.name_composition
    if not composition:
      return product.get("name", "")

    tag_map = {
      "{상품명}": product.get("name", ""),
      "{브랜드명}": product.get("brand", ""),
      "{모델명}": product.get("model_no", ""),
      "{사이트명}": product.get("source_site", ""),
      "{상품번호}": product.get("site_product_id", ""),
    }

    # 조합 태그 순서대로 값 치환
    parts = [tag_map.get(tag, tag) for tag in composition]
    composed = " ".join(p for p in parts if p and p.strip())

    # 치환어 적용
    import re
    replacements = name_rule.replacements or []
    if replacements:
      for r in replacements:
        fr = r.get("from", "") if isinstance(r, dict) else getattr(r, "from_", "")
        to = r.get("to", "") if isinstance(r, dict) else getattr(r, "to", "")
        if not fr:
          continue
        case_insensitive = r.get("caseInsensitive", False) if isinstance(r, dict) else getattr(r, "caseInsensitive", False)
        flags = re.IGNORECASE if case_insensitive else 0
        composed = re.sub(re.escape(fr), to or "", composed, flags=flags)

    # 중복 단어 제거
    if name_rule.dedup_enabled:
      words = composed.split()
      seen: set[str] = set()
      deduped: list[str] = []
      for w in words:
        lower = w.lower()
        if lower not in seen:
          seen.add(lower)
          deduped.append(w)
      composed = " ".join(deduped)

    # prefix/suffix 적용
    if name_rule.prefix:
      composed = f"{name_rule.prefix} {composed}"
    if name_rule.suffix:
      composed = f"{composed} {name_rule.suffix}"

    return composed.strip()

  # ==================== 상세페이지 HTML 생성 ====================

  async def _build_detail_html(self, product: dict[str, Any]) -> str:
    """정책의 상세 템플릿(상단/하단 이미지)과 상품 이미지를 조합하여 상세 HTML 생성.

    구조: 상단이미지 → 대표이미지 → 추가이미지 → 하단이미지
    """
    from backend.domain.samba.policy.repository import SambaPolicyRepository
    from backend.domain.samba.policy.model import SambaDetailTemplate
    from backend.domain.shared.base_repository import BaseRepository

    parts: list[str] = []
    img_tag = '<div style="text-align:center;"><img src="{url}" style="max-width:860px;width:100%;" /></div>'

    # 정책에서 상세 템플릿 조회
    policy_id = product.get("applied_policy_id")
    top_img = ""
    bottom_img = ""
    # 이미지 포함 설정 (기본값: 상단/대표/추가/하단만 포함, 상세이미지 제외)
    img_checks: dict[str, bool] = {
      "topImg": True, "main": True, "sub": True,
      "title": False, "option": False, "detail": False, "bottomImg": True,
    }
    img_order: list[str] = ["topImg", "main", "sub", "title", "option", "detail", "bottomImg"]

    if policy_id:
      policy_repo = SambaPolicyRepository(self.session)
      policy = await policy_repo.get_async(policy_id)
      if policy and policy.extras:
        template_id = policy.extras.get("detail_template_id")
        logger.info(f"[상세HTML] 정책 {policy_id} 템플릿ID: {template_id}")
        if template_id:
          tpl_repo = BaseRepository(self.session, SambaDetailTemplate)
          tpl = await tpl_repo.get_async(template_id)
          if tpl:
            top_img = tpl.top_image_s3_key or ""
            bottom_img = tpl.bottom_image_s3_key or ""
            if tpl.img_checks:
              img_checks.update(tpl.img_checks)
            if tpl.img_order:
              img_order = tpl.img_order
            logger.info(f"[상세HTML] 템플릿 로드 — 상단:{bool(top_img)}, 하단:{bool(bottom_img)}, checks:{img_checks}")
          else:
            logger.warning(f"[상세HTML] 템플릿 {template_id} 조회 실패")
      else:
        logger.info(f"[상세HTML] 정책 {policy_id} extras 없음 또는 정책 조회 실패")
    else:
      logger.info("[상세HTML] applied_policy_id 없음 — 템플릿 미적용")

    images = product.get("images") or []
    detail_images = product.get("detail_images") or []

    # img_order 순서대로, img_checks가 True인 항목만 생성
    for item_id in img_order:
      if not img_checks.get(item_id, False):
        continue
      if item_id == "topImg" and top_img:
        parts.append(img_tag.format(url=top_img))
      elif item_id == "main" and images:
        parts.append(img_tag.format(url=images[0]))
      elif item_id == "sub":
        for sub_img in images[1:]:
          parts.append(img_tag.format(url=sub_img))
      elif item_id == "title":
        name = product.get("name", "")
        if name:
          parts.append(f'<div style="text-align:center;padding:1rem 0;"><h2 style="color:#333;font-size:1.25rem;">{name}</h2></div>')
      elif item_id == "detail":
        for d_img in detail_images:
          parts.append(img_tag.format(url=d_img))
      elif item_id == "bottomImg" and bottom_img:
        parts.append(img_tag.format(url=bottom_img))

    if not parts:
      return f"<p>{product.get('name', '')}</p>"

    return "\n".join(parts)

  # ==================== 카테고리 매핑 자동 조회 ====================

  async def _resolve_category_mappings(
    self,
    source_site: str,
    source_category: str,
    target_account_ids: list[str],
  ) -> dict[str, str]:
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

    result: dict[str, str] = {}

    # 대상 계정의 마켓 타입 수집
    account_repo = SambaMarketAccountRepository(self.session)
    market_types = set()
    for aid in target_account_ids:
      acc = await account_repo.get_async(aid)
      if acc:
        market_types.add(acc.market_type)

    # cat2 코드맵이 있는 모든 마켓에서 경로 → 숫자 코드 변환 시도
    code_required_markets = market_types  # 전체 대상 마켓

    for market_type in market_types:
      # DB 매핑에 있으면 사용
      if mapping and mapping.target_mappings:
        target = mapping.target_mappings.get(market_type, "")
        if target:
          result[market_type] = target
          continue

      # DB 매핑 없으면 해당 마켓은 스킵 (사용자가 직접 매핑한 것만 전송)
      logger.info(f"[카테고리] {market_type} DB 매핑 없음 — 전송 대상에서 제외")

    # 경로 문자열 → 숫자 코드 변환 (11번가 등)
    from backend.domain.samba.category.repository import SambaCategoryTreeRepository
    category_svc = SambaCategoryService(mapping_repo, SambaCategoryTreeRepository(self.session))
    for market_type in code_required_markets:
      if market_type in result:
        cat_path = result[market_type]
        if cat_path and not cat_path.isdigit():
          code = await category_svc.resolve_category_code(market_type, cat_path)
          if code:
            logger.info("[카테고리 코드 변환] %s: '%s' → %s", market_type, cat_path, code)
            result[market_type] = code

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

  # ==================== 마켓 상품 삭제 ====================

  async def delete_from_markets(
    self,
    product_ids: list[str],
    target_account_ids: list[str],
  ) -> dict[str, Any]:
    """선택된 상품을 대상 마켓에서 판매중지/삭제."""
    from backend.domain.samba.account.repository import SambaMarketAccountRepository
    from backend.domain.samba.collector.repository import SambaCollectedProductRepository
    from backend.domain.samba.shipment.dispatcher import delete_from_market

    product_repo = SambaCollectedProductRepository(self.session)
    account_repo = SambaMarketAccountRepository(self.session)

    results: list[dict[str, Any]] = []

    for product_id in product_ids:
      product_row = await product_repo.get_async(product_id)
      if not product_row:
        results.append({"product_id": product_id, "status": "failed", "error": "상품 없음"})
        continue

      product_dict = product_row.model_dump()
      market_product_nos = product_row.market_product_nos or {}
      reg_accounts = product_row.registered_accounts or []
      delete_results: dict[str, str] = {}

      for account_id in target_account_ids:
        # 이 상품에 등록된 계정만 삭제 대상
        if account_id not in reg_accounts:
          continue

        account = await account_repo.get_async(account_id)
        if not account:
          delete_results[account_id] = "계정 없음"
          continue

        # 상품번호를 product_dict에 주입 (디스패처가 사용)
        # 스마트스토어: 삭제 API는 originProductNo 사용
        if account.market_type == "smartstore":
          product_no = market_product_nos.get(f"{account_id}_origin", "") or market_product_nos.get(account_id, "")
        else:
          product_no = market_product_nos.get(account_id, "")
        product_dict["market_product_no"] = {account.market_type: product_no}

        result = await delete_from_market(
          self.session, account.market_type, product_dict, account=account
        )

        if result.get("success"):
          delete_results[account_id] = "success"
          logger.info(
            f"[마켓삭제] {account.market_type} 성공 - 상품: {product_id}"
          )
        else:
          delete_results[account_id] = result.get("message", "실패")
          logger.warning(
            f"[마켓삭제] {account.market_type} 실패 - {result.get('message')}"
          )

      # 삭제 요청한 계정은 성공/실패 관계없이 registered_accounts에서 제거
      # (마켓에서 이미 삭제됐거나, 상품번호 없는 경우에도 등록 기록 정리)
      processed_ids = list(delete_results.keys())
      if processed_ids:
        new_reg = [a for a in reg_accounts if a not in processed_ids]
        # account_id + {account_id}_origin 모두 제거
        remove_keys = set(processed_ids)
        for aid in processed_ids:
          remove_keys.add(f"{aid}_origin")
        new_nos = {k: v for k, v in market_product_nos.items() if k not in remove_keys}
        update_data: dict[str, Any] = {
          "registered_accounts": new_reg if new_reg else None,
          "market_product_nos": new_nos if new_nos else None,
        }
        if not new_reg:
          update_data["status"] = "collected"
        await product_repo.update_async(product_id, **update_data)

      results.append({
        "product_id": product_id,
        "delete_results": delete_results,
        "success_count": len([v for v in delete_results.values() if v == "success"]),
      })

    return {
      "processed": len(results),
      "results": results,
    }

  @staticmethod
  def get_status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)
