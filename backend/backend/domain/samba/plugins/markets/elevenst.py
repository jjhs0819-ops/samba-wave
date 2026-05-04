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

        # 스토어설정 재고수량 상한 (전체 경로 공통)
        _acct_extras = (account.additional_fields or {}) if account else {}
        _max_stock_cap = int(
            _acct_extras.get("stockQuantity") or product.get("_max_stock") or 0
        )

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
                        _raw = opt.get("stock")
                        if _raw is None or _raw == "":
                            opt_stock = _max_stock_cap if _max_stock_cap > 0 else 99
                        elif int(_raw) <= 0:
                            opt_stock = 0
                        else:
                            opt_stock = (
                                min(int(_raw), _max_stock_cap)
                                if _max_stock_cap > 0
                                else int(_raw)
                            )
                        use_yn = "N" if opt_stock <= 0 else "Y"
                        stock_qty = max(0, opt_stock)
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

                _brand = (
                    (product.get("brand") or "")
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                )
                _brand_xml = f"<brand>{_brand}</brand>" if _brand else ""
                xml_data = (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    "<Product>"
                    "<selMthdCd>01</selMthdCd>"
                    f"<selPrc>{new_price}</selPrc>"
                    f"{_brand_xml}"
                    f"{option_xml}"
                    "</Product>"
                )

                logger.info(f"[11번가] 경량 업데이트 XML:\n{xml_data}")
                result = await client.update_product(existing_no, xml_data)
                logger.info(f"[11번가] 경량 업데이트 응답: {result}")

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

        # 무신사 등 referer 차단 CDN URL을 R2로 미러링
        # — 11번가는 등록 URL을 자체 서버가 fetch하므로 핫링크 차단 시 워터마크 이미지로 캐싱됨
        # — detail_html은 shipment service에서 미러링 이전에 생성되므로
        #   문자열 내부 <img src="..."> 도 같이 치환해야 워터마크 회피가 완성됨.
        try:
            from backend.domain.samba.image.service import ImageTransformService

            _img_svc = ImageTransformService(session)
            _images = product.get("images") or []
            _detail_images = product.get("detail_images") or []
            _detail_html = product.get("detail_html") or ""
            if _images or _detail_images or _detail_html:
                product = dict(product)  # 원본 dict 변형 방지
                if _images:
                    product["images"], _ = await _img_svc.mirror_external_to_r2(_images)
                if _detail_images:
                    (
                        product["detail_images"],
                        _,
                    ) = await _img_svc.mirror_external_to_r2(_detail_images)
                if _detail_html:
                    product["detail_html"] = await _img_svc.mirror_urls_in_html(
                        _detail_html
                    )
                if not product.get("images"):
                    return {
                        "success": False,
                        "message": "11번가 등록 실패: 이미지 미러링 후 사용 가능한 이미지가 없습니다.",
                    }
        except Exception as e:
            logger.warning(f"[11번가] 이미지 미러링 단계 오류 — 원본 URL 유지: {e}")

        xml_data = ElevenstClient.transform_product(
            product, cat_code, settings=account_settings
        )

        if existing_no:
            logger.info(f"[11번가] 폴백 전체XML (전체):\n{xml_data}")

        # 기존 상품번호가 있으면 수정, 없으면 신규등록
        from backend.domain.samba.proxy.elevenst import (
            ElevenstApiError,
            ElevenstRateLimitError,
        )

        try:
            if existing_no:
                result = await client.update_product(existing_no, xml_data)
                logger.info(f"[11번가] 폴백 응답: {result}")
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
