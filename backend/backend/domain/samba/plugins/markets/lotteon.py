"""롯데ON 마켓 플러그인.

기존 dispatcher._handle_lotteon 로직을 플러그인 구조로 추출.
인증 로드는 base._load_auth 가 처리하므로 execute 에서는 creds dict 사용.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.utils.logger import logger

# 브랜드명 접미사 목록 — 검색 전 자동 제거
_BRAND_SUFFIXES = ["키즈", "주니어", "주니어즈", "골프", "Kids", "Junior", "Juniors", "Golf"]


def _strip_brand_suffix(name: str) -> str:
  """브랜드명 뒤에 붙은 접미사 제거. 예: '나이키 키즈' → '나이키'"""
  for suffix in _BRAND_SUFFIXES:
    if name.endswith(" " + suffix):
      return name[:-(len(suffix) + 1)].strip()
  return name


async def _search_brand_no(client: Any, brand_name: str) -> str:
  """접미사 제거 → 첫 단어만 → 스킵 순서로 브랜드 검색. brdNo 반환."""
  stripped = _strip_brand_suffix(brand_name)
  candidates = [stripped]

  # 첫 단어만 시도 (접미사 제거 결과와 다를 때만)
  first_word = stripped.split()[0] if stripped else ""
  if first_word and first_word != stripped:
    candidates.append(first_word)

  for candidate in candidates:
    try:
      result = await client.search_brand(candidate)
      items = result.get("itemList") or result.get("data") or []
      if isinstance(items, list) and items:
        item = items[0]
        d = item.get("data", item) if isinstance(item, dict) else item
        # 브랜드 검색 응답(cheetahBrnd)의 실제 키: brnd_id
        brd_no = d.get("brnd_id", "") or d.get("brnd_no", "") or d.get("brdNo", "")
        if brd_no:
          logger.info(f"[롯데ON] 브랜드 검색 성공: {brand_name!r} → {candidate!r} brdNo={brd_no}")
          return str(brd_no)
    except Exception as e:
      logger.warning(f"[롯데ON] 브랜드 검색 실패 ({candidate!r}): {e}")

  logger.info(f"[롯데ON] 브랜드 검색 스킵 — 브랜드 공란으로 등록 진행: {brand_name!r}")
  return ""


class LotteonPlugin(MarketPlugin):
  market_type = "lotteon"
  policy_key = "롯데ON"
  required_fields = ["name", "sale_price"]

  def _validate_category(self, category_id: str) -> str:
    """롯데ON은 BC 접두사 카테고리 코드 허용 (BC41030100 형식)."""
    return category_id or ""

  def transform(self, product: dict, category_id: str, **kwargs) -> dict:
    """상품 데이터 → 롯데ON API 포맷 변환."""
    from backend.domain.samba.proxy.lotteon import LotteonClient
    tr_grp_cd = kwargs.get("tr_grp_cd", "SR")
    tr_no = kwargs.get("tr_no", "")
    return LotteonClient.transform_product(product, category_id, tr_grp_cd, tr_no)

  async def execute(
    self,
    session,
    product: dict,
    creds: dict,
    category_id: str,
    account,
    existing_no: str,
  ) -> dict[str, Any]:
    """롯데ON 상품 등록/수정 — 전체 로직."""
    from backend.domain.samba.proxy.lotteon import LotteonClient

    api_key = creds.get("apiKey", "")

    # account 필드에서 보완
    if not api_key and account:
      extras = getattr(account, "additional_fields", None) or {}
      api_key = extras.get("apiKey", "") or getattr(account, "api_key", "") or ""

    if not api_key:
      return {
        "success": False,
        "message": "롯데ON API Key가 비어있습니다. 설정에서 해당 계정을 수정 후 저장해주세요.",
      }

    # category_id가 경로 문자열(">" 포함)이면 DB 코드맵에서 변환 시도
    if category_id and ">" in category_id:
      from backend.domain.samba.category.repository import (
        SambaCategoryMappingRepository,
        SambaCategoryTreeRepository,
      )
      from backend.domain.samba.category.service import SambaCategoryService
      _cat_svc = SambaCategoryService(
        SambaCategoryMappingRepository(session),
        SambaCategoryTreeRepository(session),
      )
      resolved = await _cat_svc.resolve_category_code("lotteon", category_id)
      if resolved:
        logger.info(f"[롯데ON] 카테고리 코드 변환: '{category_id}' → {resolved}")
        category_id = resolved
      else:
        return {
          "success": False,
          "message": (
            f"롯데ON 카테고리 코드를 찾을 수 없습니다. "
            f"카테고리 설정에서 '롯데ON 동기화'를 실행한 뒤 "
            f"AI 자동 매핑을 다시 실행해주세요. "
            f"(현재 값: {category_id})"
          ),
        }

    client = LotteonClient(api_key)
    # 거래처 정보 자동 획득 (trGrpCd, trNo)
    await client.test_auth()

    product_copy = dict(product)

    # ── 1. 계정 additional_fields 주입 ──────────────────────────────
    extras: dict[str, Any] = {}
    if account:
      extras = getattr(account, "additional_fields", None) or {}

    # Settings 폴백 (계정에 출고지/배송비정책/회수지 없을 때)
    if not extras.get("owhpNo"):
      from backend.domain.samba.forbidden.model import SambaSettings
      from sqlmodel import select
      stmt = select(SambaSettings).where(SambaSettings.key == "store_lotteon")
      result = await session.execute(stmt)
      row = result.scalars().first()
      if row and isinstance(row.value, dict):
        extras = {**row.value, **extras}

    product_copy["owhp_no"] = extras.get("owhpNo", "")
    product_copy["dv_cst_pol_no"] = extras.get("dvCstPolNo", "")
    product_copy["island_dv_cst_pol_no"] = extras.get("dvIslandCstPolNo", "")
    product_copy["rtrp_no"] = extras.get("rtrpNo", "")
    product_copy["cmbn_dv_psb_yn"] = extras.get("bundleDelivery", "Y")
    # 계정 추가 설정 주입
    if extras.get("asPhone"):
      product_copy["_as_phone"] = extras["asPhone"]
    if extras.get("asMessage"):
      product_copy["_as_message"] = extras["asMessage"]
    if extras.get("discountRate"):
      product_copy["_discount_rate"] = int(extras["discountRate"])
    if extras.get("returnFee"):
      product_copy["_return_fee"] = int(extras["returnFee"])
    if extras.get("exchangeFee"):
      product_copy["_exchange_fee"] = int(extras["exchangeFee"])
    if extras.get("jejuFee"):
      product_copy["_jeju_fee"] = int(extras["jejuFee"])
    if extras.get("stockQuantity"):
      product_copy["_stock_quantity"] = int(extras["stockQuantity"])

    # ── 2. 정책 설정 주입 ────────────────────────────────────────────
    policy_id = product.get("applied_policy_id")
    if policy_id:
      from backend.domain.samba.policy.repository import SambaPolicyRepository
      policy_repo = SambaPolicyRepository(session)
      _policy = await policy_repo.get_async(policy_id)
      if _policy:
        mp = (_policy.market_policies or {}).get("롯데ON", {})
        pr = (_policy.pricing or {})
        # 배송비
        shipping = int(mp.get("shippingCost") or pr.get("shippingCost") or 0)
        if shipping > 0:
          product_copy["_delivery_fee_type"] = "PAID"
          product_copy["_delivery_base_fee"] = shipping
        # 최대 재고
        if mp.get("maxStock"):
          product_copy["_max_stock"] = int(mp["maxStock"])

    # ── 3. 브랜드 검색 (접미사 제거 → 첫 단어 → 스킵 폴백) ──────────
    brand_name = product_copy.get("brand", "")
    if brand_name and not product_copy.get("brand_no"):
      brd_no = await _search_brand_no(client, brand_name)
      if brd_no:
        product_copy["brand_no"] = brd_no

    # ── 비리프 카테고리 자동 보정 (leaf_yn="Y" 될 때까지 최대 4단계 반복 탐색) ──
    if category_id and category_id.endswith("0000"):
      logger.info(f"[롯데ON] 비리프 카테고리 감지 — 하위 탐색 시작: {category_id}")
      for _step in range(4):
        try:
          child_result = await client.get_categories(parent_id=category_id)
          child_items = child_result.get("itemList") or []
          logger.info(f"[롯데ON] 하위 카테고리 조회 결과: {len(child_items)}개 (step={_step+1})")
          if not child_items:
            logger.warning(f"[롯데ON] 비리프 보정 중단 — 하위 없음 (parent={category_id})")
            break
          d = child_items[0].get("data", child_items[0])
          child_id = d.get("std_cat_id", "") or d.get("cat_id", "") or d.get("id", "")
          leaf_yn = d.get("leaf_yn", "")
          if not child_id:
            logger.warning(f"[롯데ON] 비리프 보정 중단 — std_cat_id 없음. 키: {list(d.keys())[:10]}")
            break
          logger.info(f"[롯데ON] 비리프 자동 보정: {category_id} → {child_id} (leaf_yn={leaf_yn})")
          category_id = child_id
          if leaf_yn == "Y":
            break  # 최하위 도달
          # leaf_yn이 "N"이거나 불분명하면 한 번 더 탐색
        except Exception as e:
          logger.warning(f"[롯데ON] 하위 카테고리 조회 실패 (무시): {e}")
          break

    # 전시카테고리(FC...) 자동 조회
    disp_cat_id = ""
    try:
      cat_result = await client.get_categories(cat_id=category_id)
      items = cat_result.get("itemList") or []
      if items:
        d = items[0].get("data", {})
        disp_list = d.get("disp_list", [])
        if disp_list:
          disp_cat_id = disp_list[0].get("disp_cat_id", "")
      logger.info(f"[롯데ON] 전시카테고리 조회: {category_id} → {disp_cat_id}")
    except Exception as e:
      logger.warning(f"[롯데ON] 전시카테고리 조회 실패 (무시): {e}")

    data = LotteonClient.transform_product(
      product_copy, category_id, client.tr_grp_cd or "SR", client.tr_no, disp_cat_id
    )

    # ── 4. 등록 / 수정 ───────────────────────────────────────────────
    try:
      if existing_no:
        # ── 기존 단품 eitmNo 조회 (수정 시 중복 방지) ───────────────
        existing_eitm_nos: list[str] = []
        existing_sitm_nos: list[str] = []  # 통합EC판매자단품번호 — 살수록할인 API에서 사용
        try:
          prod_resp = await client.get_product(existing_no)
          inner = prod_resp.get("data", prod_resp)
          if isinstance(inner, dict):
            spd_info = inner.get("spdLst") or inner.get("spdInfo") or inner
            if isinstance(spd_info, list) and spd_info:
              spd_info = spd_info[0]
            if isinstance(spd_info, dict):
              itm_lst_raw = spd_info.get("itmLst") or []
              existing_eitm_nos = [
                str(itm.get("eitmNo")) for itm in itm_lst_raw if itm.get("eitmNo")
              ]
              # sitmNo = 롯데ON 내부 단품번호 (예: LO2643843825_2643843826)
              existing_sitm_nos = [
                str(itm.get("sitmNo")) for itm in itm_lst_raw if itm.get("sitmNo")
              ]
          logger.info(f"[롯데ON] 기존 단품 eitmNo: {existing_eitm_nos}, sitmNo: {existing_sitm_nos}")
        except Exception as e:
          logger.warning(f"[롯데ON] 기존 단품 조회 실패 (무시): {e}")

        # spdNo + selPrdNo 모두 주입 (롯데ON 수정 API 필수값)
        if data.get("spdLst") and isinstance(data["spdLst"], list):
          data["spdLst"][0]["spdNo"] = existing_no
          data["spdLst"][0]["selPrdNo"] = existing_no
          # 수정 API는 itmLst를 "새 단품 추가"로 처리 → 기존 옵션과 중복 에러 발생
          # 상품 헤더(이름/이미지/카테고리/가격)만 업데이트하고 itmLst는 제거
          data["spdLst"][0].pop("itmLst", None)
          data["spdLst"][0].pop("sitmYn", None)
        result = await client.update_product(data)
        # ── 수정 후 프로모션 재설정 ──────────────────────────────
        await self._apply_promotions(client, existing_no, extras, is_update=True, eitm_nos=existing_sitm_nos)
        return {"success": True, "message": "롯데ON 수정 성공", "data": result}
      else:
        result = await client.register_product(data)
        # proxy.register_product 가 spdNo를 최상위로 반환 (service.py가 result.get("spdNo")로 읽음)
        spd_no = result.get("spdNo", "") or result.get("epdNo", "")
        logger.info(f"[롯데ON] 등록 완료 — spdNo={spd_no!r}")

        # ── 등록 후 프로모션 설정: sitmNo 조회 후 전달 ────────────
        if spd_no:
          new_sitm_nos: list[str] = []
          try:
            prod_resp = await client.get_product(spd_no)
            inner = prod_resp.get("data", prod_resp)
            if isinstance(inner, dict):
              spd_info = inner.get("spdLst") or inner.get("spdInfo") or inner
              if isinstance(spd_info, list) and spd_info:
                spd_info = spd_info[0]
              if isinstance(spd_info, dict):
                new_sitm_nos = [
                  str(itm.get("sitmNo")) for itm in (spd_info.get("itmLst") or []) if itm.get("sitmNo")
                ]
          except Exception as e:
            logger.warning(f"[롯데ON] 신규 단품 sitmNo 조회 실패 (무시): {e}")
          await self._apply_promotions(client, spd_no, extras, is_update=False, eitm_nos=new_sitm_nos)

        return {"success": True, "message": "롯데ON 등록 성공", "data": result, "spdNo": spd_no}
    except Exception as e:
      action = "수정" if existing_no else "등록"
      logger.error(f"[롯데ON] {action} 실패: {e}")
      return {"success": False, "message": f"롯데ON {action} 실패: {e}"}

  async def _apply_promotions(self, client: Any, spd_no: str, extras: dict, is_update: bool = False, eitm_nos: list[str] | None = None) -> None:
    """등록/수정 후 프로모션 설정 — 실패해도 결과에 영향 없음."""

    # ── 즉시할인 ───────────────────────────────────────────────────
    discount_rate = int(extras.get("discountRate") or 0)
    if discount_rate > 0:
      try:
        resp = await client.save_immediate_discount(spd_no, discount_rate, is_update=is_update)
        logger.info(f"[롯데ON] 즉시할인 설정 완료: {discount_rate}% → {resp}")
      except Exception as e:
        logger.warning(f"[롯데ON] 즉시할인 설정 실패 (무시): {e}")

    # ── 행사 제외 설정 ──────────────────────────────────────────────
    # additional_fields 키: ownerDiscountExclude, unitCouponExclude,
    #   deliveryCouponExclude, cmPcsExclude, pcsExclude (Y/N)
    exception_flags: dict[str, str] = {}
    _flag_map = {
      "ownerDiscountExclude": "ownrDscExYn",
      "unitCouponExclude": "pdUtCpnExYn",
      "deliveryCouponExclude": "dvCpnExYn",
      "cmPcsExclude": "cmPcsDscExYn",
      "pcsExclude": "pcsDscExYn",
    }
    for settings_key, api_key in _flag_map.items():
      val = extras.get(settings_key, "")
      if val in ("Y", "N"):
        exception_flags[api_key] = val

    if exception_flags:
      try:
        resp = await client.save_product_exception(spd_no, exception_flags)
        logger.info(f"[롯데ON] 행사제외 설정 완료: {exception_flags} → {resp}")
      except Exception as e:
        logger.warning(f"[롯데ON] 행사제외 설정 실패 (무시): {e}")

    # ── L.POINT 추가적립 ────────────────────────────────────────────
    # UI 필드(purchasePointEnabled + purchasePointRate) 우선,
    # lpointAccm 직접 설정값 폴백
    purchase_enabled = extras.get("purchasePointEnabled") in (True, "true", "Y")
    lpoint_from_ui = int(extras.get("purchasePointRate") or 0) if purchase_enabled else 0
    lpoint_accm = int(extras.get("lpointAccm") or 0) or lpoint_from_ui
    if lpoint_accm > 0:
      try:
        accm_days = str(extras.get("lpointAccmDays") or "7")
        # 리뷰/사진 포인트: lpointReview/Photo 직접값 우선, UI 필드(reviewTextPoint/reviewPhotoPoint) 폴백
        lpoint_review = int(extras.get("lpointReview") or extras.get("reviewTextPoint") or 0)
        lpoint_photo = int(extras.get("lpointPhoto") or extras.get("reviewPhotoPoint") or 0)
        lpoint_video = int(extras.get("lpointVideo") or extras.get("reviewVideoPoint") or 0)
        resp = await client.save_lpoint_accumulation(
          spd_no,
          accm_val1=lpoint_accm,
          accm_vp_knd_cd=accm_days,
          accm_val2=lpoint_review,
          accm_val3=lpoint_photo,
          accm_val4=lpoint_video,
        )
        logger.info(f"[롯데ON] L.POINT 적립 설정 완료: {lpoint_accm}P (D+{accm_days}) → {resp}")
      except Exception as e:
        logger.warning(f"[롯데ON] L.POINT 적립 설정 실패 (무시): {e}")

    # ── 살수록할인 ───────────────────────────────────────────────────
    # UI 필드: multiPurchaseDiscount(설정안함/설정함) + multiPurchaseQty(수량) + multiPurchaseRate(할인율%)
    logger.info(f"[롯데ON] 살수록할인 extras 확인: multiPurchaseDiscount={extras.get('multiPurchaseDiscount')!r}, qty={extras.get('multiPurchaseQty')!r}, rate={extras.get('multiPurchaseRate')!r}")
    multi_enabled = extras.get("multiPurchaseDiscount") in ("설정함", "true", True, "Y")
    multi_qty = int(extras.get("multiPurchaseQty") or 0)
    multi_rate = float(extras.get("multiPurchaseRate") or 0)
    if multi_enabled and multi_qty > 0 and multi_rate > 0:
      try:
        resp = await client.insert_quantity_discount(spd_no, min_qty=multi_qty, discount_rate=multi_rate, eitm_nos=eitm_nos or [])
        logger.info(f"[롯데ON] 살수록할인 설정 완료: {multi_qty}개 이상 {multi_rate}% → {resp}")
      except Exception as e:
        logger.warning(f"[롯데ON] 살수록할인 설정 실패 (무시): {e}")

  async def delete(self, session, product_no: str, account) -> dict[str, Any]:
    """롯데ON 상품 판매중지 (SOUT 상태 변경)."""
    from backend.domain.samba.proxy.lotteon import LotteonClient

    creds = await self._load_auth(session, account)
    if not creds:
      return {"success": False, "message": "롯데ON 인증정보 없음"}

    api_key = creds.get("apiKey", "")
    if not api_key:
      return {"success": False, "message": "롯데ON API Key 없음"}

    try:
      client = LotteonClient(api_key)
      await client.test_auth()
      # END = 판매 종료 (롯데ON은 완전 삭제 API 없음, END가 가장 강한 종료 처리)
      await client.change_status([{"spdNo": product_no, "slStatCd": "SOUT"}])
      return {"success": True, "message": "롯데ON 판매종료 완료"}
    except Exception as e:
      logger.error(f"[롯데ON] 판매종료 실패: {e}")
      return {"success": False, "message": f"롯데ON 판매종료 실패: {e}"}
