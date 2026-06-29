"""현대홈쇼핑(Hmall) 마켓 플러그인.

재고 업데이트 / 판매중지 / 가격 수정 지원.
상품 등록은 Hmall 파트너시스템(partner.hmall.com)에서 수동 등록 후
slitmCd를 market_product_nos['hmall']에 저장해야 한다.
"""

from __future__ import annotations

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.utils.logger import logger


def _build_client(account: Any):
    """account 객체에서 HmallClient 생성."""
    from backend.domain.samba.proxy.hmall import HmallClient

    extras = getattr(account, "additional_fields", None) or {}
    # APIM ID (이메일) → oauserId 헤더 + XML body userId
    oauser_id = extras.get("apiId", "") or getattr(account, "api_key", "") or ""
    oause_key = extras.get("apiKey", "") or getattr(account, "api_secret", "") or ""
    # 협력사코드 → venCd (XML body venCd + 주문조회)
    ven_cd = extras.get("storeId", "") or getattr(account, "seller_id", "") or ""
    biz_name = extras.get("businessName", "") or ""

    if not oauser_id or not oause_key:
        return None

    return HmallClient(
        oauser_id=oauser_id,
        oause_key=oause_key,
        user_id=oauser_id,  # XML body userId = APIM ID
        ven_cd=ven_cd,
        user_nm=biz_name,
    )


class HmallPlugin(MarketPlugin):
    """현대홈쇼핑(Hmall) 마켓 플러그인."""

    market_type = "hmall"
    policy_key = "HMALL"
    required_fields = ["name", "sale_price"]

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        return {}

    async def execute(
        self,
        session,
        product: dict,
        creds: dict,
        category_id: str,
        account,
        existing_no: str,
    ) -> dict[str, Any]:
        """Hmall 상품 등록은 파트너시스템 수동 등록이 필요.

        slitmCd가 있으면 재고/가격 업데이트 실행.
        없으면 안내 메시지 반환.
        """
        slitm_cd = existing_no or (
            (product.get("market_product_nos") or {}).get("hmall", "")
        )
        if not slitm_cd:
            return {
                "success": False,
                "message": (
                    "Hmall 상품코드(slitmCd) 없음. "
                    "partner.hmall.com에서 수동 등록 후 상품번호를 입력해 주세요."
                ),
            }

        client = _build_client(account)
        if not client:
            return {"success": False, "message": "Hmall 인증정보(apiId/apiKey) 없음"}

        try:
            # 재고 조회 후 addQty 방식으로 재고 세팅
            stock_qty = int(
                (creds or {}).get("stockQuantity")
                or (getattr(account, "additional_fields", None) or {}).get(
                    "stockQuantity"
                )
                or 999
            )
            units = await client.get_unit_stocks(slitm_cd)
            if not units:
                return {
                    "success": False,
                    "message": f"Hmall 속성 정보 없음: {slitm_cd}",
                }

            update_units = [
                {
                    "uitmCd": u.get("uitmCd", ""),
                    "addQty": 0,
                    "maxSellPossQty": stock_qty,
                    "sellGbcd": u.get("sellGbcd", "00"),
                    "stckGdYn": "N",
                }
                for u in units
            ]
            await client.update_stock(slitm_cd, update_units)
            logger.info(
                f"[Hmall] 재고 업데이트 완료: {slitm_cd} x {len(update_units)}속성"
            )
            return {"success": True, "product_no": slitm_cd}

        except Exception as e:
            logger.error(f"[Hmall] execute 실패 ({slitm_cd}): {e}", exc_info=True)
            return {"success": False, "message": str(e)}

    async def delete(
        self,
        session,
        product_no: str,
        account: Any = None,
    ) -> dict[str, Any]:
        """Hmall 판매중지 — 판매구분 변경(10=중지) + 전시상태 수정."""
        if not product_no:
            return {"success": False, "message": "Hmall 상품코드 없음 (건너뜀)"}

        client = _build_client(account)
        if not client:
            return {"success": False, "message": "Hmall 인증정보 없음"}

        try:
            # 판매구분 변경: 10=판매중지
            await client.change_sell_status([product_no], sell_gbcd="10")
            logger.info(f"[Hmall] 판매중지 완료: {product_no}")
            return {"success": True}
        except Exception as e:
            logger.error(f"[Hmall] 판매중지 실패 ({product_no}): {e}", exc_info=True)
            return {"success": False, "message": str(e)}

    async def update_stock(
        self,
        session,
        product_no: str,
        stock_qty: int,
        account: Any = None,
    ) -> dict[str, Any]:
        """오토튠용 재고 업데이트."""
        if not product_no:
            return {"success": False, "message": "Hmall 상품코드 없음"}

        client = _build_client(account)
        if not client:
            return {"success": False, "message": "Hmall 인증정보 없음"}

        try:
            units = await client.get_unit_stocks(product_no)
            if not units:
                return {"success": False, "message": f"Hmall 속성 없음: {product_no}"}

            update_units = [
                {
                    "uitmCd": u.get("uitmCd", ""),
                    "addQty": 0,
                    "maxSellPossQty": stock_qty,
                    "sellGbcd": u.get("sellGbcd", "00"),
                    "stckGdYn": "N" if stock_qty > 0 else "Y",
                }
                for u in units
            ]
            await client.update_stock(product_no, update_units)
            logger.info(f"[Hmall] 재고 업데이트: {product_no} → {stock_qty}")
            return {"success": True}
        except Exception as e:
            logger.error(
                f"[Hmall] 재고 업데이트 실패 ({product_no}): {e}", exc_info=True
            )
            return {"success": False, "message": str(e)}
