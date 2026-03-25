"""롯데ON 마켓 플러그인.

기존 dispatcher._handle_lotteon 로직을 플러그인 구조로 추출.
인증 로드는 base._load_auth 가 처리하므로 execute 에서는 creds dict 사용.
"""

from __future__ import annotations

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.utils.logger import logger


class LotteonPlugin(MarketPlugin):
  market_type = "lotteon"
  policy_key = "롯데ON"
  required_fields = ["name", "sale_price"]

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
    product_copy["island_dv_cst_pol_no"] = extras.get("islandDvCstPolNo", "")
    product_copy["rtrp_no"] = extras.get("rtrpNo", "")
    product_copy["cmbn_dv_psb_yn"] = extras.get("cmbnDvPsbYn", "Y")

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

    # ── 3. 브랜드 검색 연동 ──────────────────────────────────────────
    brand_name = product_copy.get("brand", "")
    if brand_name and not product_copy.get("brand_no"):
      try:
        brand_result = await client.search_brand(brand_name)
        # 응답 구조: data[0].brdNo
        brand_list = (brand_result.get("data") or [])
        if isinstance(brand_list, list) and brand_list:
          brd_no = brand_list[0].get("brdNo", "")
          if brd_no:
            product_copy["brand_no"] = str(brd_no)
            logger.info(f"[롯데ON] 브랜드 검색 성공: {brand_name} → brdNo={brd_no}")
      except Exception as e:
        logger.warning(f"[롯데ON] 브랜드 검색 실패 (무시): {e}")

    data = LotteonClient.transform_product(
      product_copy, category_id, client.tr_grp_cd or "SR", client.tr_no
    )

    # ── 4. 등록 / 수정 ───────────────────────────────────────────────
    try:
      if existing_no:
        # selPrdNo 주입하여 수정 요청
        if data.get("spdLst") and isinstance(data["spdLst"], list):
          data["spdLst"][0]["selPrdNo"] = existing_no
        result = await client.update_product(data)
        return {"success": True, "message": "롯데ON 수정 성공", "data": result}
      else:
        result = await client.register_product(data)
        # 등록 결과에서 상품번호 추출
        spd_no = result.get("spdNo", "")
        return {"success": True, "message": "롯데ON 등록 성공", "data": result, "product_no": spd_no}
    except Exception as e:
      action = "수정" if existing_no else "등록"
      logger.error(f"[롯데ON] {action} 실패: {e}")
      return {"success": False, "message": f"롯데ON {action} 실패: {e}"}

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
      # SOUT = 품절/판매중지
      await client.change_status([{"selPrdNo": product_no, "slStatCd": "SOUT"}])
      return {"success": True, "message": "롯데ON 판매중지 완료"}
    except Exception as e:
      logger.error(f"[롯데ON] 판매중지 실패: {e}")
      return {"success": False, "message": f"롯데ON 판매중지 실패: {e}"}
