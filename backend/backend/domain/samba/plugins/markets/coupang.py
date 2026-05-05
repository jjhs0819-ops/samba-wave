"""쿠팡 마켓 플러그인.

기존 dispatcher._handle_coupang 로직을 플러그인 구조로 추출.
인증 로드는 base._load_auth 가 처리하므로 execute 에서는 creds dict 사용.
"""

from __future__ import annotations

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.utils.logger import logger


class CoupangPlugin(MarketPlugin):
    market_type = "coupang"
    policy_key = "쿠팡"
    required_fields = ["name", "sale_price"]

    def _validate_category(self, category_id: str) -> str:
        """쿠팡은 비숫자 카테고리(경로 문자열)도 허용 — resolve_category_code 로 동적 조회."""
        return category_id

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        """상품 데이터 → 쿠팡 API 포맷 변환."""
        from backend.domain.samba.proxy.coupang import CoupangClient

        return CoupangClient.transform_product(
            product,
            category_id,
            return_center_code=kwargs.get("return_center_code", ""),
            outbound_shipping_place_code=kwargs.get("outbound_shipping_place_code", ""),
        )

    async def execute(
        self,
        session,
        product: dict,
        creds: dict,
        category_id: str,
        account,
        existing_no: str,
    ) -> dict[str, Any]:
        """쿠팡 상품 등록/수정 — 전체 로직."""
        from backend.domain.samba.proxy.coupang import CoupangClient

        access_key = creds.get("accessKey", "")
        secret_key = creds.get("secretKey", "")
        vendor_id = creds.get("vendorId", "")

        # account 필드에서 보완
        if account:
            access_key = access_key or getattr(account, "api_key", "") or ""
            secret_key = secret_key or getattr(account, "api_secret", "") or ""
            vendor_id = vendor_id or getattr(account, "seller_id", "") or ""

        if not access_key or not secret_key:
            return {
                "success": False,
                "message": "쿠팡 Access Key/Secret Key가 없습니다.",
            }

        if not vendor_id:
            return {
                "success": False,
                "message": "쿠팡 Vendor ID가 없습니다. 계정 설정을 확인해주세요.",
            }

        client = CoupangClient(access_key, secret_key, vendor_id)

        # ── 경량 가격/재고 업데이트 (오토튠 최적화) ──────────────────────
        # _skip_image_upload=True → price/stock만 변경된 경우
        # 반품지/출고지/카테고리 조회 없이 기존 상품 가격/재고만 수정
        if product.get("_skip_image_upload") and existing_no:
            try:
                existing = await client.get_product(existing_no)
                prod_data = existing.get("data", existing)
                if isinstance(prod_data, dict):
                    items = prod_data.get("items") or []
                else:
                    items = []

                if not items:
                    logger.warning(
                        f"[쿠팡] 경량 업데이트 실패 — items 없음, 전체 수정으로 폴백: {existing_no}"
                    )
                else:
                    new_price = int(product.get("sale_price", 0)) // 10 * 10
                    new_options = product.get("options") or []
                    opt_stock_map = {
                        (o.get("name", "") or o.get("size", "") or ""): o.get(
                            "stock", 999
                        )
                        for o in new_options
                    }

                    for item in items:
                        # 가격 업데이트
                        if new_price > 0:
                            item["originalPrice"] = new_price
                            item["salePrice"] = new_price
                        # 재고 업데이트 (옵션명으로 매칭)
                        item_name = item.get("itemName", "")
                        if item_name in opt_stock_map:
                            stk = opt_stock_map[item_name]
                        elif new_options:
                            stk = min(
                                (o.get("stock", 999) for o in new_options),
                                default=999,
                            )
                        else:
                            stk = 999
                        item["maximumBuyCount"] = min(int(stk), 99999)

                    prod_data["items"] = items
                    await client.update_product(existing_no, prod_data)

                    _parts = []
                    if new_price > 0:
                        _parts.append(f"가격({new_price:,}원)")
                    if new_options:
                        _parts.append(f"옵션({len(new_options)}건)")
                    logger.info(
                        f"[쿠팡] 경량 업데이트 완료: {existing_no} — {', '.join(_parts)}"
                    )
                    return {
                        "success": True,
                        "product_no": existing_no,
                        "message": f"쿠팡 경량 업데이트: {', '.join(_parts)}",
                        "data": {"sellerProductId": existing_no},
                    }

            except Exception as e:
                logger.warning(
                    f"[쿠팡] 경량 업데이트 실패, 전체 수정으로 폴백: {existing_no} — {e}"
                )
                # 폴백: 아래 전체 로직으로 계속 진행

        # 카테고리 코드가 숫자가 아니면 쿠팡 API로 동적 조회
        if category_id and not str(category_id).isdigit():
            resolved = await client.resolve_category_code(category_id)
            category_id = str(resolved) if resolved else ""

        # vendorUserId: Wing 로그인 ID (seller_id 사용)
        vendor_user_id = ""
        if account:
            vendor_user_id = getattr(account, "seller_id", "") or ""

        # 계정별 사전 저장된 출고지/반품지 코드 읽기 (다계정 자연 지원)
        extras = (account.additional_fields or {}) if account else {}
        if not isinstance(extras, dict):
            extras = {}
        outbound_code = str(extras.get("outboundShippingPlaceCode", "") or "")
        return_center_code = str(extras.get("returnCenterCode", "") or "")
        return_address = str(extras.get("returnCenterAddress", "") or "")
        return_address_detail = str(extras.get("returnCenterAddressDetail", "") or "")
        return_zipcode = str(extras.get("returnCenterZipcode", "") or "")
        return_phone = str(extras.get("returnCenterPhone", "") or "")

        if not outbound_code or not return_center_code:
            return {
                "success": False,
                "message": "쿠팡 설정에서 출고지/반품지를 먼저 조회 후 선택해주세요.",
            }

        # 카테고리별 정확한 noticeCategoryName/Detail을 쿠팡 메타 API로 동적 조회
        # — 의류/신발 등록 시 정적 매핑이 쿠팡 표준과 미스매치되어 옵션 notice가 거부되는
        # 문제(2026-05 보고)의 근본 해결. 실패 시 transform_product 내부에서 정적 매핑 폴백.
        notice_meta = None
        if category_id and str(category_id).isdigit():
            try:
                notice_meta = await client.get_notice_categories(str(category_id))
            except Exception as _e:
                # 메타 조회 실패는 등록 자체를 막지 않음 — fallback 사용
                pass

        # AS 전화번호 주입은 base._apply_market_settings 에서 처리됨
        data = CoupangClient.transform_product(
            product,
            category_id,
            return_center_code=return_center_code,
            outbound_shipping_place_code=outbound_code,
            notice_meta=notice_meta,
        )
        data["vendorId"] = vendor_id
        data["vendorUserId"] = vendor_user_id or vendor_id

        # 반품지 실제 주소 정보 덮어쓰기 (캐시된 값 사용)
        if return_zipcode:
            data["returnZipCode"] = return_zipcode
        if return_address:
            data["returnAddress"] = return_address
        if return_address_detail:
            data["returnAddressDetail"] = return_address_detail
        if return_phone:
            data["companyContactNumber"] = return_phone

        # 기존 상품번호가 있으면 수정, 없으면 신규등록
        if existing_no:
            result = await client.update_product(existing_no, data)
            return {
                "success": True,
                "product_no": existing_no,
                "message": "쿠팡 수정 성공",
                "data": {"sellerProductId": existing_no},
            }
        else:
            result = await client.register_product(data)

            # 쿠팡 응답에서 sellerProductId 추출 (data 필드에 숫자로 반환)
            seller_product_id = ""
            if isinstance(result, dict):
                inner = result.get("data", {})
                if isinstance(inner, dict):
                    seller_product_id = str(inner.get("data", ""))
                elif inner:
                    seller_product_id = str(inner)

            return {
                "success": True,
                "product_no": seller_product_id,
                "message": "쿠팡 등록 성공",
                "data": {"sellerProductId": seller_product_id}
                if seller_product_id
                else result,
            }
