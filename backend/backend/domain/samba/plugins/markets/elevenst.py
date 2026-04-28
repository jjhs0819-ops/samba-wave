"""11번가 마켓 플러그인.

기존 dispatcher._handle_11st 로직을 플러그인 구조로 추출.
인증 로드는 base._load_auth 가 처리하므로 execute 에서는 creds dict 사용.
"""

from __future__ import annotations

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.utils.logger import logger


class ElevenstPlugin(MarketPlugin):
    market_type = "11st"
    policy_key = "11번가"
    required_fields = ["name", "sale_price"]

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        """상품 데이터 → 11번가 XML 포맷 변환."""
        from backend.domain.samba.proxy.elevenst import ElevenstClient

        settings = kwargs.get("settings", {})
        return ElevenstClient.transform_product(product, category_id, settings=settings)

    async def execute(
        self,
        session,
        product: dict,
        creds: dict,
        category_id: str,
        account,
        existing_no: str,
    ) -> dict[str, Any]:
        """11번가 상품 등록/수정 — 전체 로직."""
        from backend.domain.samba.proxy.elevenst import ElevenstClient

        api_key = creds.get("apiKey", "")

        # account 필드에서 보완
        if not api_key and account:
            api_key = getattr(account, "api_key", "") or ""

        if not api_key:
            return {
                "success": False,
                "message": "11번가 API Key가 비어있습니다. 설정에서 해당 계정을 수정 후 저장해주세요.",
            }

        # 카테고리 코드가 숫자가 아니면 (경로 문자열이면) 빈값 처리
        cat_code = category_id
        if cat_code and not cat_code.isdigit():
            cat_code = ""

        if not cat_code:
            return {
                "success": False,
                "message": "11번가 카테고리 코드가 없습니다. 카테고리 매핑을 설정해주세요.",
            }

        client = ElevenstClient(api_key)

        # ── 경량 가격/재고 업데이트 (오토튠 최적화) ──────────────────────
        # _skip_image_upload=True → price/stock만 변경된 경우
        # 전체 XML 변환 없이 가격/재고만 포함된 최소 XML로 수정
        if product.get("_skip_image_upload") and existing_no:
            from backend.domain.samba.proxy.elevenst import ElevenstRateLimitError

            try:
                new_price = int(product.get("sale_price", 0))
                options = product.get("options") or []

                # 공식 11번가 상품수정 API 스펙: ProductOption 구조 사용
                # (sellerOptions/sellerOption은 비공식 구조로 옵션 덮어쓰기 오작동 위험)
                option_xml = ""
                if options:
                    # colTitle: 최초 등록 시 사용한 옵션 타입명 유지 (기본: 옵션)
                    col_title = product.get("option_type") or "옵션"
                    col_title = col_title[:25]  # 11번가 최대 25자 제한
                    option_xml = (
                        "<optSelectYn>Y</optSelectYn>"
                        "<txtColCnt>1</txtColCnt>"
                        f"<colTitle>{col_title}</colTitle>"
                        "<prdExposeClfCd>00</prdExposeClfCd>"
                    )
                    for opt in options:
                        opt_name = opt.get("name", "") or opt.get("size", "") or "기본"
                        opt_stock = opt.get("stock", 999)
                        use_yn = "N" if int(opt_stock) <= 0 else "Y"
                        stock_qty = max(0, int(opt_stock))
                        stock_code = opt.get("managedCode", "") or ""
                        # XML 특수문자 이스케이프
                        safe_name = (
                            opt_name.replace("&", "&amp;")
                            .replace("<", "&lt;")
                            .replace(">", "&gt;")
                            .replace('"', "&quot;")
                            .replace("'", "&apos;")
                        )
                        safe_code = (
                            stock_code.replace("&", "&amp;")
                            .replace("<", "&lt;")
                            .replace(">", "&gt;")
                        )
                        option_xml += (
                            "<ProductOption>"
                            f"<useYn>{use_yn}</useYn>"
                            f"<colOptPrice>0</colOptPrice>"
                            f"<colValue0>{safe_name}</colValue0>"
                            f"<colCount>{stock_qty}</colCount>"
                            f"<colSellerStockCd>{safe_code}</colSellerStockCd>"
                            "</ProductOption>"
                        )

                xml_data = (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    "<Product>"
                    f"<selPrc>{new_price}</selPrc>"
                    f"{option_xml}"
                    "</Product>"
                )

                result = await client.update_product(existing_no, xml_data)

                _parts = [f"가격({new_price:,}원)"]
                if options:
                    _parts.append(f"옵션({len(options)}건)")
                logger.info(
                    f"[11번가] 경량 업데이트 완료: {existing_no} — {', '.join(_parts)}"
                )
                return {
                    "success": True,
                    "product_no": existing_no,
                    "message": f"11번가 경량 업데이트: {', '.join(_parts)}",
                    "data": result,
                }

            except ElevenstRateLimitError:
                raise  # Rate Limit은 폴백 없이 즉시 전파
            except Exception as e:
                logger.warning(
                    f"[11번가] 경량 업데이트 실패, 전체 수정으로 폴백: {existing_no} — {e}"
                )
                # 폴백: 아래 전체 로직으로 계속 진행

        account_settings = (account.additional_fields or {}) if account else {}
        xml_data = ElevenstClient.transform_product(
            product, cat_code, settings=account_settings
        )

        # 기존 상품번호가 있으면 수정, 없으면 신규등록
        from backend.domain.samba.proxy.elevenst import (
            ElevenstApiError,
            ElevenstRateLimitError,
        )

        try:
            if existing_no:
                result = await client.update_product(existing_no, xml_data)
                return {
                    "success": True,
                    "product_no": existing_no,
                    "message": "11번가 수정 성공",
                    "data": result,
                }
            else:
                result = await client.register_product(xml_data)
                prd_no = result.get("prd_no") or result.get("data", {}).get("prdNo", "")
                if not prd_no:
                    logger.warning(
                        f"[11번가] 신규 등록 후 prdNo 미수신 — result keys={list(result.keys()) if isinstance(result, dict) else type(result)}"
                    )
                else:
                    logger.info(f"[11번가] 신규 등록 완료 — product_no={prd_no}")
                return {
                    "success": True,
                    "product_no": prd_no,
                    "message": "11번가 등록 성공",
                    "data": result,
                }
        except ElevenstRateLimitError:
            raise  # worker까지 전파시켜 Rate Limit 동적 감소 동작하도록
        except ElevenstApiError as e:
            err = str(e)
            if "해외 쇼핑 카테고리" in err:
                return {
                    "success": False,
                    "message": f"카테고리 오류: 코드 {cat_code}가 해외쇼핑 카테고리입니다. 카테고리매핑에서 국내 카테고리 코드로 수정해주세요.",
                }
            return {"success": False, "message": f"11번가 등록 실패: {err}"}
