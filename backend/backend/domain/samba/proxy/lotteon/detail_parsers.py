"""롯데ON 상세 페이지 파싱 믹스인.

상세 페이지 HTML/JSON에서 상품 정보를 추출하는 파서 메서드와
공통 유틸리티 메서드를 제공한다.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from backend.domain.samba.proxy.lotteon.category_map import _LOTTEON_SCAT_NAMES
from backend.utils.logger import logger


class DetailParsersMixin:
    """상세 페이지 파싱 + 공통 유틸리티 메서드 믹스인."""

    # 하위 클래스에서 정의되는 상수 (타입 힌트용)
    PRODUCT_URL: str

    # ------------------------------------------------------------------
    # 공통 헬퍼
    # ------------------------------------------------------------------

    def _normalize_image(self, url: str) -> str:
        """이미지 URL 정규화 (프로토콜 보정)."""
        if not url:
            return ""
        url = url.strip()
        if url.startswith("//"):
            return f"https:{url}"
        if not url.startswith("http"):
            return ""
        return url

    @staticmethod
    def _extract_meta(html: str, prop: str) -> Optional[str]:
        """og/product 메타 태그에서 content 추출."""
        pattern = (
            rf'<meta[^>]+(?:property|name)="{re.escape(prop)}"[^>]+content="([^"]*)"'
        )
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            return m.group(1)
        # content가 먼저 오는 경우
        pattern2 = (
            rf'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="{re.escape(prop)}"'
        )
        m2 = re.search(pattern2, html, re.IGNORECASE)
        return m2.group(1) if m2 else None

    @staticmethod
    def _extract_text(html: str, pattern: str) -> str:
        """정규식으로 텍스트 추출."""
        m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _extract_price(html: str, pattern: str) -> int:
        """정규식으로 가격(숫자) 추출."""
        m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if m:
            digits = re.sub(r"[^\d]", "", m.group(1))
            return int(digits) if digits else 0
        return 0

    @staticmethod
    def _safe_int(value: Any) -> int:
        """안전한 정수 변환."""
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            digits = re.sub(r"[^\d]", "", value)
            return int(digits) if digits else 0
        return 0

    # ------------------------------------------------------------------
    # HTML에서 sitmNo 추출
    # ------------------------------------------------------------------

    def _extract_sitmno_from_html(self, html: str) -> str:
        """HTML에서 sitmNo 추출 (HTML 엔티티 디코딩 후 파싱)."""
        import html as html_module

        decoded = html_module.unescape(html)
        m = re.search(r'"sitmNo"\s*:\s*"([A-Z]{2}[0-9]+_[0-9]+)"', decoded)
        return m.group(1) if m else ""

    # ------------------------------------------------------------------
    # PBF 보완 메서드
    # ------------------------------------------------------------------

    def _enrich_from_pbf(self, detail: dict[str, Any], pbf: dict[str, Any]) -> None:
        """pbf API 데이터로 detail dict 보완 (옵션/재고/이미지/가격/카테고리)."""
        # ── 가격 보완 ──────────────────────────────────────────────
        price_info = pbf.get("priceInfo") or {}
        sl_prc = self._safe_int(price_info.get("slPrc", 0))

        # ── 최대혜택가 계산 (판매가 - 즉시할인 - 추가할인) ─────────
        immd_dc = self._safe_int(price_info.get("immdDcAplyTotAmt", 0))
        adtn_dc = self._safe_int(price_info.get("adtnDcAplyTotAmt", 0))

        if immd_dc > 0 or adtn_dc > 0:
            # PBF에 할인 정보 있음 → slPrc 기준으로 가격 갱신
            if sl_prc > 0:
                detail["salePrice"] = sl_prc
            base_prc = sl_prc or detail.get("salePrice", 0)
            if base_prc > 0:
                best_benefit = base_prc - immd_dc - adtn_dc
                if best_benefit > 0 and best_benefit < base_prc:
                    detail["bestBenefitPrice"] = best_benefit
                else:
                    detail["bestBenefitPrice"] = base_prc
        elif sl_prc > 0:
            # PBF에 할인 정보 없음 → slPrc가 정상가(할인 전)일 수 있으므로
            # 기존 JSON-LD/HTML 파싱값이 더 낮으면 보존
            existing_sale = detail.get("salePrice", 0)
            if existing_sale <= 0:
                detail["salePrice"] = sl_prc
            existing_bbp = detail.get("bestBenefitPrice", 0)
            if existing_bbp <= 0:
                detail["bestBenefitPrice"] = existing_sale or sl_prc

        # ── 카테고리 코드 저장 (딕셔너리 매핑은 폴백용으로만 보존) ──
        # 우선순위: dispCategoryInfo(전시 카테고리) > scatNo 딕셔너리(내부 분류)
        # dispCategoryInfo가 실제 사이트 브레드크럼과 일치하므로 우선 사용
        basic = pbf.get("basicInfo") or {}
        logger.debug(f"[LOTTEON] pbf basicInfo keys: {list(basic.keys())}")
        scat_no = str(basic.get("scatNo", "") or "").strip()
        if scat_no:
            # 팀장 카테고리 룰 매핑용으로 scatNo 보존
            detail["_lotteonScatNo"] = scat_no
            # 딕셔너리 매핑값은 폴백용으로만 보존 (dispCategoryInfo 우선)
            cat_name = _LOTTEON_SCAT_NAMES.get(scat_no, "")
            if cat_name:
                detail["_scatCategoryFallback"] = cat_name

        # ── 브랜드 보완 (basicInfo.brdNm) ──────────────────────────
        brd_nm = str(basic.get("brdNm", "") or "").strip()
        if brd_nm and not detail.get("brand"):
            detail["brand"] = brd_nm

        # ── 스펙 필드 (basicInfo 다중 후보 키) ─────────────────────
        _SPEC_CANDIDATES: dict[str, list[str]] = {
            "manufacturer": ["mfrNm", "mfr", "manufacturerNm", "manufacturerName"],
            "origin": ["orgNm", "origin", "originNm", "madeIn", "madeInNm"],
            "sex": ["sexTpCd", "genderType", "sex"],
            "season": ["seasnCd", "season"],
            "color": ["colorNm", "colorName", "color"],
            "material": ["materialNm", "material"],
            "style_code": ["styleNo", "modelNo", "styleCode"],
            "care_instructions": ["careInstructions"],
        }
        for field, candidates in _SPEC_CANDIDATES.items():
            if not detail.get(field):
                for cand in candidates:
                    val = str(basic.get(cand, "") or "").strip()
                    if val:
                        if field == "sex":
                            val = self._normalize_sex(val)
                        detail[field] = val
                        break

        # ── 재고 ──────────────────────────────────────────────────
        stck = pbf.get("stckInfo") or {}
        stk_qty = stck.get("stkQty")
        is_out = stk_qty is not None and stk_qty == 0
        if stk_qty is not None:
            detail["isOutOfStock"] = is_out
            detail["isSoldOut"] = is_out
            detail["saleStatus"] = "sold_out" if is_out else "in_stock"

        # ── 옵션 ──────────────────────────────────────────────────
        # 기존 옵션의 실재고(stockQty)를 옵션명으로 매핑 — pbf는 disabled 플래그만
        # 있고 옵션별 재고 수량이 없으므로, 기존 파싱값을 보존한다.
        _existing_stock_map: dict[str, int] = {}
        for _eo in detail.get("options") or []:
            _ename = _eo.get("name", "")
            _estock = _eo.get("stock", 0)
            if _ename and _estock > 0:
                _existing_stock_map[_ename] = _estock

        opt_info = pbf.get("optionInfo") or {}
        option_groups = opt_info.get("optionList") or []
        options: list[dict[str, Any]] = []

        if option_groups:
            # 단일 옵션 그룹 (사이즈/색상)
            primary_group = option_groups[0]
            for opt in primary_group.get("options", []):
                label = opt.get("label", "").strip()
                if not label:
                    continue
                disabled = bool(opt.get("disabled", False))
                # 기존 옵션에 실재고가 있으면 보존, 없으면 pbf 기본값 사용
                _prev_stock = _existing_stock_map.get(label, 0)
                _stock = (
                    0
                    if disabled
                    else (_prev_stock if _prev_stock > 0 else (stk_qty or 99))
                )
                options.append(
                    {
                        "no": len(options),
                        "name": label,
                        "price": sl_prc or detail.get("salePrice", 0),
                        "stock": _stock,
                        "isSoldOut": disabled,
                    }
                )

            # 멀티 옵션 그룹 (색상 + 사이즈) — label 조합
            if len(option_groups) >= 2:
                options = []
                for g1_opt in option_groups[0].get("options", []):
                    for g2_opt in option_groups[1].get("options", []):
                        combined_disabled = g1_opt.get("disabled", False) or g2_opt.get(
                            "disabled", False
                        )
                        combined_label = f"{g1_opt.get('label', '')} / {g2_opt.get('label', '')}".strip(
                            " /"
                        )
                        _prev_stock = _existing_stock_map.get(combined_label, 0)
                        _stock = (
                            0
                            if combined_disabled
                            else (_prev_stock if _prev_stock > 0 else (stk_qty or 99))
                        )
                        options.append(
                            {
                                "no": len(options),
                                "name": combined_label,
                                "price": sl_prc or detail.get("salePrice", 0),
                                "stock": _stock,
                                "isSoldOut": bool(combined_disabled),
                            }
                        )

        if options:
            detail["options"] = options

        # ── 이미지 보완 ────────────────────────────────────────────
        img_info = pbf.get("imgInfo") or {}
        img_list = img_info.get("imageList") or []
        pbf_images: list[str] = []
        for img in img_list:
            path = img.get("imgRteNm", "") + img.get("imgFileNm", "")
            if path:
                full_url = f"https://contents.lotteon.com/itemimage{path}"
                pbf_images.append(self._normalize_image(full_url))

        if pbf_images and not detail.get("images"):
            detail["images"] = pbf_images[:9]
        elif pbf_images and len(detail.get("images", [])) < 2:
            detail["images"] = pbf_images[:9]

    def _enrich_from_pbf_pd(
        self, detail: dict[str, Any], pd_data: dict[str, Any]
    ) -> None:
        """pbf /base/pd/ API 데이터로 고시정보(artlInfo) + 카테고리 보완."""
        # ── artlInfo (상품필수정보/고시정보) ──────────────────────────
        artl = pd_data.get("artlInfo") or {}
        artl_list = artl.get("pdItmsArtlJsn") or []

        # artlInfo 필드명 → detail 키 매핑
        _ARTL_MAP: dict[str, str] = {
            "색상": "color",
            "제조국": "origin",
            # 소재/재질 (카테고리별 필드명이 다름)
            "제품소재": "material",
            "제품 주소재": "material",
            "상품 주소재": "material",
            "소재": "material",
            "재질": "material",
            "주소재": "material",
            # 제조사
            "제조자, 수입자": "manufacturer",
            "제조자(수입자)": "manufacturer",
            "제조자": "manufacturer",
            # 세탁/취급 (카테고리별 필드명이 다름)
            "세탁방법 및 취급시 주의사항": "care_instructions",
            "취급시 주의사항": "care_instructions",
            "취급 시 주의사항": "care_instructions",
            "세탁방법": "care_instructions",
            # 기타
            "품질보증기준": "quality_guarantee",
            "A/S책임자와 전화번호": "as_contact",
            "제조년월": "manufacture_date",
        }

        for item in artl_list:
            nm = (item.get("pdArtlCdNm") or "").strip()
            val = (item.get("pdArtlCnts") or "").strip()
            if not nm or not val:
                continue
            # 무의미한 값 제외 (단, 색상은 괄호 앞 실제 값 추출 시도)
            if "별 상이" in val or val in ("해당없음", "해당 없음", "-", "없음"):
                continue
            # "상세페이지 참조" 패턴 처리
            if "상세" in val and "참조" in val:
                # 색상: "블랙(상세페이지 이미지참조)" → "블랙" 추출
                target = _ARTL_MAP.get(nm)
                if target == "color" and "(" in val:
                    color_part = val.split("(")[0].strip()
                    if color_part and not detail.get("color"):
                        detail["color"] = color_part
                continue
            target = _ARTL_MAP.get(nm)
            if target and not detail.get(target):
                detail[target] = val

        if artl_list:
            logger.debug(f"[LOTTEON] artlInfo 파싱: {len(artl_list)}개 항목")

        # ── 카테고리별 기본값 보완 (SEO 최적화) ────────────────────────
        # artlInfo에 "상품상세페이지 참조"만 있거나 필드 자체가 없는 경우 기본 문구 삽입
        artl_cat_cd = artl.get(
            "pdItmsCd", ""
        )  # "01"=의류, "02"=구두/신발, "03"=가방 등
        _DEFAULT_CARE: dict[str, str] = {
            "01": (
                "찬물에 단독 손세탁을 권장합니다. "
                "세탁 시 뒤집어서 세탁하고, 표백제 사용을 피해주세요. "
                "건조기 사용을 삼가고 그늘에서 건조해 주세요."
            ),
            "02": (
                "오염 시 부드러운 솔이나 젖은 천으로 가볍게 닦아주세요. "
                "세탁기 사용을 피하고, 직사광선을 피해 통풍이 잘 되는 곳에서 건조해 주세요."
            ),
            "03": (
                "오염 시 부드러운 천으로 가볍게 닦아주세요. "
                "물세탁을 피하고, 직사광선을 피해 서늘한 곳에 보관해 주세요."
            ),
            "04": (
                "오염 시 부드러운 천으로 가볍게 닦아주세요. "
                "물세탁을 피하고, 직사광선을 피해 서늘한 곳에 보관해 주세요."
            ),
        }
        if not detail.get("care_instructions") and artl_cat_cd:
            default_care = _DEFAULT_CARE.get(artl_cat_cd)
            if default_care:
                detail["care_instructions"] = default_care

        # ── 상품명에서 소재 힌트 추출 (material 비어있을 때) ────────────
        if not detail.get("material"):
            product_name = detail.get("name", "")
            _MATERIAL_HINTS: dict[str, str] = {
                "스웨이드": "스웨이드",
                "suede": "스웨이드",
                "레더": "천연가죽",
                "leather": "천연가죽",
                "메시": "메시",
                "mesh": "메시",
                "캔버스": "캔버스",
                "canvas": "캔버스",
                "데님": "데님",
                "denim": "데님",
                "플리스": "폴리에스터(플리스)",
                "fleece": "폴리에스터(플리스)",
                "니트": "니트",
                "knit": "니트",
                "우븐": "우븐",
                "woven": "우븐",
            }
            name_lower = product_name.lower()
            for hint, mat_val in _MATERIAL_HINTS.items():
                if hint.lower() in name_lower:
                    detail["material"] = mat_val
                    break

        # ── dispCategoryInfo (전시 카테고리 — 사이트 브레드크럼과 동일) ──
        # 실제 롯데ON 사이트에 표시되는 카테고리이므로 최우선 적용
        disp_cat = pd_data.get("dispCategoryInfo") or {}
        if disp_cat:
            parts = []
            for key in ["dispCatNm", "dispCatNm0", "dispCatNm1", "dispCatNm2"]:
                nm = (disp_cat.get(key) or "").strip()
                if nm:
                    parts.append(nm)
            if parts:
                detail["category"] = " > ".join(parts)
                for i, part in enumerate(parts[:4], 1):
                    detail[f"category{i}"] = part

        # dispCategoryInfo가 없으면 scatNo 딕셔너리 폴백 적용
        if not detail.get("category") and detail.get("_scatCategoryFallback"):
            cat_name = detail["_scatCategoryFallback"]
            detail["category"] = cat_name
            parts = cat_name.split(" > ")
            for i, part in enumerate(parts[:4], 1):
                detail[f"category{i}"] = part

    # ------------------------------------------------------------------
    # JSON-LD 파싱 (상세)
    # ------------------------------------------------------------------

    def _parse_json_ld_detail(
        self,
        html: str,
        product_no: str,
        now_iso: str,
        timestamp: int,
    ) -> Optional[dict[str, Any]]:
        """JSON-LD(schema.org Product) 마크업에서 상품 상세 데이터 추출."""
        json_ld_pattern = re.compile(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            re.DOTALL,
        )

        for m in json_ld_pattern.finditer(html):
            try:
                ld_data = json.loads(m.group(1))
                # 배열인 경우 Product 타입 찾기
                if isinstance(ld_data, list):
                    for item in ld_data:
                        if isinstance(item, dict) and item.get("@type") == "Product":
                            ld_data = item
                            break
                    else:
                        continue

                if not isinstance(ld_data, dict):
                    continue
                if ld_data.get("@type") != "Product":
                    continue

                name = ld_data.get("name", "")
                if not name:
                    continue

                # 가격 정보
                offers = ld_data.get("offers", {})
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}

                sale_price = self._safe_int(offers.get("price", 0))
                original_price = (
                    self._safe_int(offers.get("highPrice", 0)) or sale_price
                )

                # 재고 상태
                availability = offers.get("availability", "")
                is_out_of_stock = (
                    "OutOfStock" in availability if availability else False
                )

                # 이미지
                raw_images = ld_data.get("image", [])
                if isinstance(raw_images, str):
                    raw_images = [raw_images]
                images = [
                    self._normalize_image(img)
                    for img in raw_images
                    if self._normalize_image(img)
                ][:9]

                # 브랜드
                brand_obj = ld_data.get("brand", {})
                brand = (
                    brand_obj.get("name", "")
                    if isinstance(brand_obj, dict)
                    else str(brand_obj)
                )

                # 카테고리 (JSON-LD에는 보통 없음 → HTML에서 보완)
                category_levels = self._parse_category(html)
                category_str = " > ".join(category_levels) if category_levels else ""

                # 옵션 (JSON-LD에는 보통 없음 → HTML에서 보완)
                options = self._parse_options(html)

                # 상세 이미지
                detail_images = self._parse_detail_images(html)

                # 배송 정보
                free_shipping = bool(
                    re.search(
                        r"(?:무료배송|무료 배송|배송비\s*무료)", html, re.IGNORECASE
                    )
                )
                same_day_delivery = bool(
                    re.search(
                        r"(?:당일배송|새벽배송|바로배송|오늘배송)", html, re.IGNORECASE
                    )
                )

                # 품절 재확인 (HTML 기반)
                if not is_out_of_stock:
                    is_out_of_stock = self._check_sold_out(html, options)

                sale_status = "sold_out" if is_out_of_stock else "in_stock"

                return {
                    "id": f"col_lotteon_{product_no}_{timestamp}",
                    "sourceSite": "LOTTEON",
                    "siteProductId": str(product_no),
                    "sourceUrl": f"{self.PRODUCT_URL}/{product_no}",
                    "name": name.strip(),
                    "brand": brand.strip() if brand else "",
                    "category": category_str,
                    "category1": category_levels[0] if len(category_levels) > 0 else "",
                    "category2": category_levels[1] if len(category_levels) > 1 else "",
                    "category3": category_levels[2] if len(category_levels) > 2 else "",
                    "category4": category_levels[3] if len(category_levels) > 3 else "",
                    "images": images[:9],
                    "detailImages": detail_images,
                    "options": options,
                    "originalPrice": original_price,
                    "salePrice": sale_price,
                    "bestBenefitPrice": self._parse_best_benefit_price(html)
                    or sale_price,
                    "saleStatus": sale_status,
                    "isOutOfStock": is_out_of_stock,
                    "freeShipping": free_shipping,
                    "sameDayDelivery": same_day_delivery,
                    "collectedAt": now_iso,
                    "updatedAt": now_iso,
                    "manufacturer": "",
                    "origin": "",
                    "sex": "",
                    "season": "",
                    "color": "",
                    "material": "",
                    "style_code": self._extract_style_code_from_name(name.strip()),
                    "care_instructions": "",
                    "quality_guarantee": "",
                    "shipping_fee": 0,
                }

            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.debug(f"[LOTTEON] JSON-LD 파싱 스킵: {e}")
                continue

        return None

    # ------------------------------------------------------------------
    # __NEXT_DATA__ 파싱 (상세)
    # ------------------------------------------------------------------

    def _parse_next_data_detail(
        self,
        html: str,
        product_no: str,
        now_iso: str,
        timestamp: int,
    ) -> Optional[dict[str, Any]]:
        """__NEXT_DATA__ JSON에서 상품 상세 데이터 추출."""
        next_data_match = re.search(
            r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        )
        if not next_data_match:
            return None

        try:
            next_data = json.loads(next_data_match.group(1))
            page_props = next_data.get("props", {}).get("pageProps", {})

            # 상품 데이터 경로 탐색
            product: dict[str, Any] = {}
            for key_path in [
                ("product",),
                ("productDetail",),
                ("initialState", "product"),
                ("data", "product"),
            ]:
                obj = page_props
                for key in key_path:
                    obj = obj.get(key, {}) if isinstance(obj, dict) else {}
                if isinstance(obj, dict) and obj:
                    product = obj
                    break

            if not product:
                return None

            name = (
                product.get("productName", "")
                or product.get("spdNm", "")
                or product.get("name", "")
            )
            if not name:
                return None

            # 가격 정보
            sale_price = self._safe_int(
                product.get("salePrice", 0)
                or product.get("sellPrc", 0)
                or product.get("price", 0)
            )
            original_price = (
                self._safe_int(
                    product.get("originalPrice", 0) or product.get("norPrc", 0)
                )
                or sale_price
            )
            best_benefit_price = (
                self._safe_int(
                    product.get("bestBenefitPrice", 0) or product.get("bestPrice", 0)
                )
                or sale_price
            )

            # 브랜드
            brand = product.get("brandName", "") or product.get("brandNm", "") or ""

            # 이미지
            images: list[str] = []
            main_image = product.get("mainImageUrl", "") or product.get(
                "mainImgUrl", ""
            )
            if main_image:
                images.append(self._normalize_image(main_image))
            for img in (
                product.get("addImageUrls", []) or product.get("addImgUrls", []) or []
            ):
                img_url = self._normalize_image(
                    img if isinstance(img, str) else img.get("url", "")
                )
                if img_url and img_url not in images:
                    images.append(img_url)

            # 카테고리
            category_levels: list[str] = []
            for key in [
                "category1Name",
                "category2Name",
                "category3Name",
                "category4Name",
            ]:
                val = product.get(key, "") or product.get(key.replace("Name", "Nm"), "")
                if val:
                    category_levels.append(val)
            if not category_levels:
                category_levels = self._parse_category(html)
            category_str = " > ".join(category_levels) if category_levels else ""

            # 옵션
            options: list[dict[str, Any]] = []
            raw_options = (
                product.get("options", []) or product.get("optionList", []) or []
            )
            for opt in raw_options:
                opt_name = (
                    opt.get("optionName", "")
                    or opt.get("optNm", "")
                    or opt.get("name", "")
                ).strip()
                if not opt_name:
                    continue

                opt_price = self._safe_int(
                    opt.get("price", 0) or opt.get("sellPrc", 0) or opt.get("addPrc", 0)
                )
                opt_stock = self._safe_int(
                    opt.get("stockQty", 0) or opt.get("stock", 0)
                )
                is_sold_out = (
                    opt.get("soldOut", False)
                    or opt.get("soldOutYn", "N") == "Y"
                    or opt_stock == 0
                )
                options.append(
                    {
                        "name": opt_name,
                        "price": opt_price,
                        "stock": opt_stock,
                        "isSoldOut": bool(is_sold_out),
                    }
                )

            # 옵션이 __NEXT_DATA__에 없으면 HTML에서 추출
            if not options:
                options = self._parse_options(html)

            # 상세 이미지
            detail_images = self._parse_detail_images(html)

            # 품절 여부
            is_out_of_stock = (
                product.get("soldOut", False)
                or product.get("soldOutYn", "N") == "Y"
                or self._check_sold_out(html, options)
            )

            # 배송 정보
            free_shipping = bool(
                product.get("freeDelivery", False)
                or product.get("freeShipping", False)
                or re.search(
                    r"(?:무료배송|무료 배송|배송비\s*무료)", html, re.IGNORECASE
                )
            )
            same_day_delivery = bool(
                product.get("sameDayDelivery", False)
                or re.search(
                    r"(?:당일배송|새벽배송|바로배송|오늘배송)", html, re.IGNORECASE
                )
            )

            sale_status = "sold_out" if is_out_of_stock else "in_stock"

            # 스펙 필드 추출
            manufacturer = str(
                product.get("mfrNm", "")
                or product.get("manufacturerNm", "")
                or product.get("manufacturer", "")
                or ""
            ).strip()
            origin = str(
                product.get("orgNm", "")
                or product.get("originNm", "")
                or product.get("madeIn", "")
                or product.get("origin", "")
                or ""
            ).strip()
            sex_raw = str(
                product.get("sexTpCd", "")
                or product.get("genderType", "")
                or product.get("sex", "")
                or ""
            ).strip()
            sex = self._normalize_sex(sex_raw) if sex_raw else ""
            season = str(
                product.get("seasnCd", "") or product.get("season", "") or ""
            ).strip()
            color = str(
                product.get("colorNm", "")
                or product.get("colorName", "")
                or product.get("color", "")
                or ""
            ).strip()
            material = str(
                product.get("materialNm", "") or product.get("material", "") or ""
            ).strip()
            style_code = str(
                product.get("styleNo", "")
                or product.get("modelNo", "")
                or product.get("styleCode", "")
                or ""
            ).strip() or self._extract_style_code_from_name(name.strip())
            care_instructions = str(product.get("careInstructions", "") or "").strip()

            return {
                "id": f"col_lotteon_{product_no}_{timestamp}",
                "sourceSite": "LOTTEON",
                "siteProductId": str(product_no),
                "sourceUrl": f"{self.PRODUCT_URL}/{product_no}",
                "name": name.strip(),
                "brand": brand.strip(),
                "category": category_str,
                "category1": category_levels[0] if len(category_levels) > 0 else "",
                "category2": category_levels[1] if len(category_levels) > 1 else "",
                "category3": category_levels[2] if len(category_levels) > 2 else "",
                "category4": category_levels[3] if len(category_levels) > 3 else "",
                "images": images[:9],
                "detailImages": detail_images,
                "options": options,
                "originalPrice": original_price,
                "salePrice": sale_price,
                "bestBenefitPrice": best_benefit_price,
                "saleStatus": sale_status,
                "isOutOfStock": bool(is_out_of_stock),
                "freeShipping": free_shipping,
                "sameDayDelivery": same_day_delivery,
                "collectedAt": now_iso,
                "updatedAt": now_iso,
                "manufacturer": manufacturer,
                "origin": origin,
                "sex": sex,
                "season": season,
                "color": color,
                "material": material,
                "style_code": style_code,
                "care_instructions": care_instructions,
                "quality_guarantee": "",
                "shipping_fee": 0,
            }

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"[LOTTEON] __NEXT_DATA__ 상세 파싱 실패: {e}")
            return None

    # ------------------------------------------------------------------
    # 메타 태그 폴백 (상세)
    # ------------------------------------------------------------------

    def _parse_meta_detail(
        self,
        html: str,
        product_no: str,
        now_iso: str,
        timestamp: int,
    ) -> dict[str, Any]:
        """메타 태그 + HTML에서 상품 상세 정보 추출 (최종 폴백)."""
        name = self._extract_meta(html, "og:title") or ""
        thumbnail = self._normalize_image(self._extract_meta(html, "og:image") or "")

        # 가격 추출
        sale_price = self._parse_sale_price(html)
        original_price = self._parse_original_price(html)
        if original_price == 0:
            original_price = sale_price
        best_benefit_price = self._parse_best_benefit_price(html) or sale_price

        # 브랜드
        brand = self._parse_brand(html)

        # 카테고리
        category_levels = self._parse_category(html)
        category_str = " > ".join(category_levels) if category_levels else ""

        # 이미지
        images = self._parse_product_images(html, thumbnail)

        # 상세 이미지
        detail_images = self._parse_detail_images(html)

        # 옵션
        options = self._parse_options(html)

        # 품절 여부
        is_out_of_stock = self._check_sold_out(html, options)

        # 배송 정보
        free_shipping = bool(
            re.search(r"(?:무료배송|무료 배송|배송비\s*무료)", html, re.IGNORECASE)
        )
        same_day_delivery = bool(
            re.search(r"(?:당일배송|새벽배송|바로배송|오늘배송)", html, re.IGNORECASE)
        )

        sale_status = "sold_out" if is_out_of_stock else "in_stock"

        return {
            "id": f"col_lotteon_{product_no}_{timestamp}",
            "sourceSite": "LOTTEON",
            "siteProductId": str(product_no),
            "sourceUrl": f"{self.PRODUCT_URL}/{product_no}",
            "name": name.strip(),
            "brand": brand,
            "category": category_str,
            "category1": category_levels[0] if len(category_levels) > 0 else "",
            "category2": category_levels[1] if len(category_levels) > 1 else "",
            "category3": category_levels[2] if len(category_levels) > 2 else "",
            "category4": category_levels[3] if len(category_levels) > 3 else "",
            "images": images[:9],
            "detailImages": detail_images,
            "options": options,
            "originalPrice": original_price,
            "salePrice": sale_price,
            "bestBenefitPrice": best_benefit_price,
            "saleStatus": sale_status,
            "isOutOfStock": is_out_of_stock,
            "freeShipping": free_shipping,
            "sameDayDelivery": same_day_delivery,
            "collectedAt": now_iso,
            "updatedAt": now_iso,
            "manufacturer": "",
            "origin": "",
            "sex": "",
            "season": "",
            "color": "",
            "material": "",
            "style_code": self._extract_style_code_from_name(name.strip()),
            "care_instructions": "",
            "quality_guarantee": "",
            "shipping_fee": 0,
        }

    # ------------------------------------------------------------------
    # 스펙 헬퍼
    # ------------------------------------------------------------------

    def _parse_spec_table(self, html: str) -> dict[str, str]:
        """HTML th-td 쌍에서 스펙 테이블 파싱 (제조사/원산지/소재 등)."""
        KEY_MAP: dict[str, str] = {
            "제조사": "manufacturer",
            "수입사": "manufacturer",
            "제조자": "manufacturer",
            "제조자, 수입자": "manufacturer",
            "수입자": "manufacturer",
            "제조국": "origin",
            "원산지": "origin",
            "소재": "material",
            "재질": "material",
            "성별": "sex",
            "시즌": "season",
            "색상": "color",
            "컬러": "color",
            "품번": "style_code",
            "모델번호": "style_code",
            "취급주의": "care_instructions",
            "세탁": "care_instructions",
            "취급시 주의사항": "care_instructions",
        }
        GARBAGE = {
            "상세설명참조",
            "상세페이지참조",
            "상품상세참조",
            "상품상세 참조",
            "-",
            "없음",
            "해당없음",
            "n/a",
            "별도표기",
            "상세페이지 참조",
        }
        result: dict[str, str] = {}
        for th, td in re.findall(
            r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>",
            html,
            re.DOTALL | re.IGNORECASE,
        ):
            key = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", th)).strip()
            val = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", td)).strip()
            if not key or not val:
                continue
            if val.lower() in GARBAGE:
                continue
            mapped = KEY_MAP.get(key)
            if mapped and mapped not in result:
                result[mapped] = val
        return result

    def _extract_style_code_from_name(self, name: str) -> str:
        """상품명에서 품번 추출 (브랜드별 패턴 + 일반 폴백)."""
        SPECIFIC = [
            # 빈폴: BC6341C66H, BC5941C20A_LL (옵션 접미사 _XX 허용)
            r"(?<![A-Z0-9])(BC\d{4}[A-Z]\d{2}[A-Z])(?:_[A-Z]{1,3})?(?![A-Z0-9])",
            # 나이키: CD6404-105, HF0015-002
            r"\b([A-Z]{2}\d{4}-\d{3})\b",
            # 라코스테: BF702E-56G-X6F
            r"\b([A-Z]{2}\d{3}[A-Z]-\d{2}[A-Z]-[A-Z]\d[A-Z])\b",
            # MLB: 3ATSB0163-50BKS
            r"\b(\d[A-Z]{4}\d{4}-\d{2}[A-Z]{3})\b",
            # 뉴발란스: NBNEG21203_60
            r"\b(NB[A-Z]{3,6}\d{3,5}[A-Z]?_\d{2})\b",
            r"\b(NB[A-Z]{3,6}\d{3,5}[A-Z]?)\b",
            # 푸마: 528564-48
            r"\b(\d{6}-\d{2})\b",
            # 노스페이스: NJ3LQ37B (옵션 접미사 _CRE 허용)
            r"(?<![A-Z0-9])(N[A-Z]\d[A-Z]{2}\d{2}[A-Z])(?:_[A-Z]{2,4})?(?![A-Z0-9])",
            # 헤지스: HSJU6BC21
            r"\b(HS[A-Z]{2}\d[A-Z]{2}\d{2})\b",
            # 디스커버리: (DXSH5545N)
            r"\(?(DX[A-Z]{2}\d{4}[A-Z])\)?",
            # 타미: T32G0WJC10TWL1 (T로 시작 14자 영숫자 혼합)
            r"\b(T\d{2}[A-Z0-9]{11})\b",
            # 폴로: MNPOSWE16822569020
            r"\b([A-Z]{4,8}\d{10,18})\b",
            # 아디다스/일반: KC2649, AB12345
            r"\b([A-Z]{2,3}\d{4,5}[A-Z]?\d?)\b",
        ]
        BLACKLIST_PREFIX = {"LO", "PD", "LE", "SS", "FW"}
        for pattern in SPECIFIC:
            for m in re.finditer(pattern, name):
                code = m.group(1)
                if code[:2] in BLACKLIST_PREFIX:
                    continue
                return code
        return ""

    def _extract_season_from_name(self, name: str) -> str:
        """상품명에서 시즌 추출 — [SS26], [26SS], SS26, 26SS 등 모든 형식 지원."""
        SEASONS = r"SS|FW|SP|SU|AU|WI|HOL"
        # 1) [SS26] / SS26
        m = re.search(rf"\[?({SEASONS})(\d{{2}})\]?", name, re.IGNORECASE)
        if m:
            return f"{m.group(1).upper()}{m.group(2)}"
        # 2) [26SS] / 26SS
        m = re.search(rf"\[?(\d{{2}})({SEASONS})\]?", name, re.IGNORECASE)
        if m:
            return f"{m.group(2).upper()}{m.group(1)}"
        return ""

    def _infer_sex(self, name: str, brand: str, category1: str, category: str) -> str:
        """상품명/브랜드/카테고리에서 성별 추정."""
        haystack = " ".join([name or "", brand or "", category1 or "", category or ""])
        if re.search(
            r"남녀\s*공용|남여\s*공용|공용|유니섹스|unisex|UNISEX",
            haystack,
            re.IGNORECASE,
        ):
            return "남녀공용"
        if re.search(
            r"여성|여자|레이디(스|즈)?|우먼|women|woman|ladies",
            haystack,
            re.IGNORECASE,
        ):
            return "여성"
        if re.search(r"남성|남자|\b멘\b|men|man|mens", haystack, re.IGNORECASE):
            return "남성"
        return ""

    def _normalize_sex(self, val: str) -> str:
        """성별 값 정규화."""
        v = val.strip().lower()
        if v in {"남녀공용", "공용", "unisex"}:
            return "남녀공용"
        if v in {"여성", "여자", "women", "woman"}:
            return "여성"
        if v in {"남성", "남자", "men", "man"}:
            return "남성"
        return val.strip()

    # ------------------------------------------------------------------
    # HTML 보완 (JSON-LD 결과에 누락된 정보 채우기)
    # ------------------------------------------------------------------

    def _enrich_from_html(self, detail: dict[str, Any], html: str) -> None:
        """JSON-LD 파싱 결과에 누락된 정보를 HTML에서 보완."""
        # 최대혜택가가 판매가와 동일하면 HTML에서 재탐색
        if detail.get("bestBenefitPrice", 0) == detail.get("salePrice", 0):
            benefit = self._parse_best_benefit_price(html)
            if benefit and benefit < detail["salePrice"]:
                detail["bestBenefitPrice"] = benefit

        # 이미지가 부족하면 HTML에서 추가 수집
        if len(detail.get("images", [])) < 3:
            thumbnail = detail["images"][0] if detail.get("images") else ""
            html_images = self._parse_product_images(html, thumbnail)
            for img in html_images:
                if img not in detail["images"]:
                    detail["images"].append(img)
                    if len(detail["images"]) >= 9:
                        break

        # 스펙 테이블 파싱 (이미 채워진 필드는 덮어쓰지 않음)
        spec = self._parse_spec_table(html)
        for field, val in spec.items():
            if not detail.get(field):
                if field == "sex":
                    val = self._normalize_sex(val)
                detail[field] = val

    # ------------------------------------------------------------------
    # 가격 파싱 헬퍼
    # ------------------------------------------------------------------

    def _parse_sale_price(self, html: str) -> int:
        """판매가 추출.

        메타 태그 → HTML 가격 영역 순서로 탐색.
        """
        # 메타 태그 우선
        price_meta = self._extract_meta(html, "product:price:amount")
        if price_meta:
            price = self._safe_int(re.sub(r"[^\d]", "", price_meta))
            if price > 0:
                return price

        # 롯데ON 판매가 영역
        for pattern in [
            r'class="[^"]*sale[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*sell[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*final[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*product[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
        ]:
            price = self._extract_price(html, pattern)
            if price > 0:
                return price

        return 0

    def _parse_original_price(self, html: str) -> int:
        """정상가(원래 가격) 추출."""
        for pattern in [
            r'class="[^"]*origin[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*original[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*old[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*normal[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
        ]:
            price = self._extract_price(html, pattern)
            if price > 0:
                return price

        return 0

    def _parse_best_benefit_price(self, html: str) -> int:
        """최대혜택가 추출 (쿠폰+적립금 포함)."""
        for pattern in [
            r'class="[^"]*best[_-]?benefit[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*coupon[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r"(?:최대혜택가|쿠폰적용가|최저가)[^<]*?(\d[\d,]+)",
            r'class="[^"]*benefit[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
        ]:
            price = self._extract_price(html, pattern)
            if price > 0:
                return price

        return 0

    # ------------------------------------------------------------------
    # 정보 파싱 헬퍼
    # ------------------------------------------------------------------

    def _parse_brand(self, html: str) -> str:
        """브랜드명 추출."""
        for pattern in [
            r'class="[^"]*brand[_-]?name[^"]*"[^>]*>([^<]+)',
            r'class="[^"]*brand[_-]?area[^"]*"[^>]*>\s*<a[^>]*>([^<]+)',
            r'class="[^"]*product[_-]?brand[^"]*"[^>]*>([^<]+)',
        ]:
            brand = self._extract_text(html, pattern)
            if brand:
                return brand.strip()

        return ""

    def _parse_category(self, html: str) -> list[str]:
        """카테고리 경로 추출 (깊이별 리스트).

        롯데ON 상품 페이지의 브레드크럼 또는 카테고리 네비게이션에서 추출.
        """
        categories: list[str] = []

        # 브레드크럼 영역에서 추출
        breadcrumb_pattern = re.compile(
            r'class="[^"]*breadcrumb[^"]*"[^>]*>(.*?)</(?:ul|ol|div|nav)',
            re.DOTALL | re.IGNORECASE,
        )
        breadcrumb = breadcrumb_pattern.search(html)
        if breadcrumb:
            link_texts = re.findall(
                r"<a[^>]*>([^<]+)</a>",
                breadcrumb.group(1),
            )
            for text in link_texts:
                text = text.strip()
                if text and text not in ("홈", "HOME", "롯데ON", "전체"):
                    categories.append(text)

        # 브레드크럼이 없으면 카테고리 메타 태그
        if not categories:
            cat_meta = self._extract_meta(html, "product:category")
            if cat_meta:
                categories = [c.strip() for c in cat_meta.split(">") if c.strip()]

        # 카테고리 네비게이션 영역에서 추출
        if not categories:
            cat_pattern = re.compile(
                r'class="[^"]*cate[_-]?path[^"]*"[^>]*>(.*?)</(?:div|ul)',
                re.DOTALL | re.IGNORECASE,
            )
            cat_match = cat_pattern.search(html)
            if cat_match:
                cat_texts = re.findall(r">([^<]+)<", cat_match.group(1))
                categories = [
                    t.strip()
                    for t in cat_texts
                    if t.strip() and t.strip() not in ("홈", ">", "/", "롯데ON")
                ]

        return categories[:4]

    def _parse_product_images(self, html: str, thumbnail: str) -> list[str]:
        """상품 이미지 목록 추출 (대표 이미지 포함, 최대 9장)."""
        images: list[str] = []
        if thumbnail:
            images.append(thumbnail)

        # 롯데ON 이미지 갤러리 영역
        gallery_pattern = re.compile(
            r'class="[^"]*(?:product[_-]?gallery|thumb[_-]?list|image[_-]?slide)[^"]*"[^>]*>(.*?)</(?:div|ul)',
            re.DOTALL | re.IGNORECASE,
        )
        gallery = gallery_pattern.search(html)
        target = gallery.group(1) if gallery else html

        # contents.lotteon.com CDN 이미지 패턴
        img_pattern = re.compile(
            r'(?:src|data-src|data-lazy)=["\']([^"\']*(?:contents\.lotteon\.com|lotteon\.com/p/img)[^"\']+)["\']',
            re.IGNORECASE,
        )
        for m in img_pattern.finditer(target):
            img_url = self._normalize_image(m.group(1))
            if img_url and img_url not in images:
                images.append(img_url)
                if len(images) >= 9:
                    break

        # CDN 이미지 부족 시 일반 이미지도 수집
        if len(images) < 3:
            general_img_pattern = re.compile(
                r'class="[^"]*product[_-]?img[^"]*"[^>]*>.*?<img[^>]+src="([^"]+)"',
                re.DOTALL | re.IGNORECASE,
            )
            for m in general_img_pattern.finditer(html):
                img_url = self._normalize_image(m.group(1))
                if img_url and img_url not in images:
                    images.append(img_url)
                    if len(images) >= 9:
                        break

        return images[:9]

    def _parse_detail_images(self, html: str) -> list[str]:
        """상세 설명 영역에서 이미지 URL 추출."""
        images: list[str] = []

        # 롯데ON 상세 설명 영역
        detail_area = re.search(
            r'(?:id="[^"]*detail[_-]?cont[^"]*"|class="[^"]*detail[_-]?content[^"]*"|class="[^"]*product[_-]?detail[^"]*")[^>]*>(.*)',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        if detail_area:
            img_pattern = re.compile(r'<img[^>]+src="([^"]+)"', re.IGNORECASE)
            for m in img_pattern.finditer(detail_area.group(1)):
                img_url = self._normalize_image(m.group(1))
                if img_url and img_url not in images:
                    images.append(img_url)

        return images

    def _parse_options(self, html: str) -> list[dict[str, Any]]:
        """옵션 정보 추출.

        롯데ON 옵션은 JSON 데이터 또는 셀렉트박스로 제공된다.
        """
        options: list[dict[str, Any]] = []

        # 방법 1: 옵션 JSON 데이터에서 추출
        option_json_pattern = re.compile(
            r"(?:optionData|optionList|itemOptList)\s*[=:]\s*(\[.*?\]);",
            re.DOTALL,
        )
        json_match = option_json_pattern.search(html)
        if json_match:
            try:
                option_list = json.loads(json_match.group(1))
                for opt in option_list:
                    opt_name = (
                        opt.get("optNm", "")
                        or opt.get("optionName", "")
                        or opt.get("name", "")
                    ).strip()
                    if not opt_name:
                        continue

                    opt_price = self._safe_int(
                        opt.get("sellPrc", 0)
                        or opt.get("addPrc", 0)
                        or opt.get("price", 0)
                    )
                    opt_stock = self._safe_int(
                        opt.get("stockQty", 0) or opt.get("stock", 0)
                    )
                    is_sold_out = (
                        opt.get("soldOutYn", "N") == "Y"
                        or opt.get("soldOut", False)
                        or opt.get("isSoldOut", False)
                        or opt_stock == 0
                    )

                    options.append(
                        {
                            "no": len(options),
                            "name": opt_name,
                            "price": opt_price,
                            "stock": opt_stock,
                            "isSoldOut": bool(is_sold_out),
                        }
                    )
                return options
            except (json.JSONDecodeError, TypeError):
                pass

        # 방법 2: 셀렉트박스에서 옵션 추출
        option_area = re.search(
            r'class="[^"]*option[_-]?select[^"]*"[^>]*>(.*?)</select>',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        if option_area:
            option_pattern = re.compile(
                r'<option[^>]+value="([^"]*)"[^>]*>([^<]+)</option>',
                re.IGNORECASE,
            )
            matches = option_pattern.findall(option_area.group(1))
            for value, text in matches:
                text = text.strip()
                # 플레이스홀더 제외
                if not value or "선택" in text:
                    continue

                # 품절 여부
                is_sold_out = "품절" in text

                # 가격 정보 추출 (옵션명에 포함된 경우)
                price_in_option = 0
                price_match = re.search(r"\(([+-]?\d[\d,]*)\)", text)
                if price_match:
                    price_in_option = self._safe_int(
                        re.sub(r"[^\d\-]", "", price_match.group(1))
                    )

                options.append(
                    {
                        "no": len(options),
                        "name": text,
                        "price": price_in_option,
                        "stock": 0 if is_sold_out else 1,
                        "isSoldOut": is_sold_out,
                    }
                )

        return options

    def _check_sold_out(self, html: str, options: list[dict[str, Any]]) -> bool:
        """품절 여부 판단.

        1. HTML에 품절 표시가 있는 경우
        2. 모든 옵션이 품절인 경우
        """
        # HTML 내 품절 마커
        if re.search(
            r'class="[^"]*sold[_-]?out[^"]*"',
            html,
            re.IGNORECASE,
        ):
            return True

        # 명시적 품절 텍스트 (구매 버튼 영역)
        button_area = re.search(
            r'class="[^"]*(?:buy[_-]?btn|purchase[_-]?btn|cart[_-]?btn)[^"]*"[^>]*>(.*?)</div>',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        if button_area and re.search(
            r"(?:품절|일시품절|SOLD\s*OUT)",
            button_area.group(1),
            re.IGNORECASE,
        ):
            return True

        # 옵션이 있고 모두 품절인 경우
        if options and all(opt.get("isSoldOut", False) for opt in options):
            return True

        return False
