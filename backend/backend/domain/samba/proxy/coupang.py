"""쿠팡 Wing API 클라이언트 - 상품 등록/수정.

인증 방식: HMAC-SHA256
- method, url, timestamp, accessKey → HMAC 서명 생성
- Authorization: CEA algorithm=HmacSHA256, access-key={accessKey}, signed-date={datetime}, signature={signature}
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from backend.core.config import settings
from backend.utils.logger import logger

# ------------------------------------------------------------------
# SEO 헬퍼 함수 (모듈 레벨)
# ------------------------------------------------------------------

# 노출상품명 불용어
_DISPLAY_NAME_STOPWORDS = {
    "무료배송",
    "당일발송",
    "특가",
    "할인",
    "세일",
    "SALE",
    "신상",
    "인기",
    "추천",
    "베스트",
    "HOT",
    "NEW",
    "한정",
    "사은품",
}

# 사이즈 패턴 (숫자 2~3자리, 알파벳 사이즈, FREE 등)
_SIZE_PATTERN = re.compile(
    r"^(\d{2,3}(?:\([A-Za-z]+\))?|(?:XX?[SL]|[SML]|FREE))$", re.IGNORECASE
)


def _build_display_product_name(product: dict[str, Any]) -> str:
    """쿠팡 노출상품명 생성 (최대 100자).

    우선순위: market_names["쿠팡"] → 자동생성
    자동생성: 브랜드 + 성별 + 카테고리키워드 + 특성 + 품번
    """
    # 수동 설정된 쿠팡 노출상품명 우선
    market_names = product.get("market_names") or {}
    if isinstance(market_names, dict) and market_names.get("쿠팡"):
        return str(market_names["쿠팡"])[:100]

    parts: list[str] = []

    # 브랜드
    brand = (product.get("brand") or "").strip()
    if brand:
        parts.append(brand)

    # 성별
    sex = (product.get("sex") or "").strip()
    sex_map = {
        "남성": "남성",
        "여성": "여성",
        "남": "남성",
        "여": "여성",
        "M": "남성",
        "F": "여성",
        "MALE": "남성",
        "FEMALE": "여성",
        "공용": "공용",
        "남녀공용": "남녀공용",
    }
    mapped_sex = sex_map.get(sex, "")
    if mapped_sex:
        parts.append(mapped_sex)

    # 카테고리 키워드 (category4 → 3 → 2 우선)
    for key in ("category4", "category3", "category2"):
        cat_val = (product.get(key) or "").strip()
        if cat_val and cat_val not in parts:
            parts.append(cat_val)
            break

    # 원본 상품명에서 특성 추출 (브랜드/카테고리 제외, 불용어 제외)
    original_name = product.get("name") or ""
    name_tokens = re.split(r"[\s/\-_]+", original_name)
    existing_lower = {p.lower() for p in parts}
    for token in name_tokens:
        token_clean = token.strip()
        if (
            len(token_clean) >= 2
            and token_clean not in _DISPLAY_NAME_STOPWORDS
            and token_clean.lower() not in existing_lower
        ):
            parts.append(token_clean)
            existing_lower.add(token_clean.lower())
            # 특성은 최대 3개까지
            if len(parts) >= 7:
                break

    # 품번 (style_code)
    style_code = (product.get("style_code") or "").strip()
    if style_code and style_code.lower() not in existing_lower:
        parts.append(style_code)

    result = " ".join(parts)

    # 100자 초과 시 품번 유지하고 중간 잘라내기
    if len(result) > 100 and style_code:
        max_body = 100 - len(style_code) - 1  # 공백 1자
        body = " ".join(parts[:-1])
        result = body[:max_body].rstrip() + " " + style_code
    return result[:100]


def _build_search_tags(product: dict[str, Any]) -> str:
    """쿠팡 검색어 태그 생성 (최대 20개, 콤마 구분, 각 20자 이내).

    추출 우선순위: 브랜드 → seo_keywords → 카테고리 → 상품명 단어 → 품번 → 소재/색상
    """
    seen: set[str] = set()
    tags: list[str] = []

    def _add(keyword: str) -> None:
        kw = keyword.strip()
        if len(kw) < 2 or len(kw) > 20:
            return
        kw_lower = kw.lower()
        if kw_lower in seen or kw in _DISPLAY_NAME_STOPWORDS:
            return
        seen.add(kw_lower)
        tags.append(kw)

    # 브랜드
    brand = (product.get("brand") or "").strip()
    if brand:
        _add(brand)

    # SEO 키워드
    seo_keywords = product.get("seo_keywords") or []
    if isinstance(seo_keywords, list):
        for kw in seo_keywords:
            _add(str(kw))

    # 카테고리 (4→3→2→1)
    for key in ("category4", "category3", "category2", "category1"):
        cat_val = (product.get(key) or "").strip()
        if cat_val:
            _add(cat_val)

    # 상품명 단어 분리
    original_name = product.get("name") or ""
    name_tokens = re.split(r"[\s/\-_,()]+", original_name)
    for token in name_tokens:
        _add(token)

    # 품번
    style_code = (product.get("style_code") or "").strip()
    if style_code:
        _add(style_code)

    # 소재/색상
    material = (product.get("material") or "").strip()
    if material:
        _add(material)
    color = (product.get("color") or "").strip()
    if color:
        _add(color)

    return ",".join(tags[:20])


def _parse_option_color_size(opt_name: str, default_color: str) -> tuple[str, str]:
    """옵션명에서 색상/사이즈 분리.

    "블랙 / 090(S)" → ("블랙", "090(S)")
    "Black/M" → ("Black", "M")
    "L" → (default_color, "L")
    "레드" → ("레드", "FREE")
    """
    opt_name = opt_name.strip()
    if not opt_name:
        return default_color, "FREE"

    # 구분자로 분리 시도 (/ 또는 ,)
    parts = re.split(r"\s*/\s*|\s*,\s*", opt_name)
    parts = [p.strip() for p in parts if p.strip()]

    if len(parts) >= 2:
        # 2개 이상이면 마지막이 사이즈인지 확인
        last = parts[-1]
        if _SIZE_PATTERN.match(last):
            color_part = " ".join(parts[:-1])
            return color_part or default_color, last
        # 첫번째가 사이즈인지 확인
        first = parts[0]
        if _SIZE_PATTERN.match(first):
            color_part = " ".join(parts[1:])
            return color_part or default_color, first
        # 둘다 사이즈 아니면 첫번째=색상, 마지막=사이즈
        return parts[0], parts[-1]

    # 단일값
    single = parts[0] if parts else opt_name
    if _SIZE_PATTERN.match(single):
        return default_color, single
    # 사이즈 패턴 아니면 색상으로 간주
    return single, "FREE"


def _build_content_details(detail_html: str) -> list[dict[str, Any]]:
    """상세 HTML에서 IMAGE/TEXT 혼합 contentDetails 생성.

    <img src="..."> 태그 기준으로 분할하여 TEXT/IMAGE 블록 교차 배치.
    img 없으면 기존 방식(TEXT 단일 블록) 유지.
    """
    if not detail_html:
        return [{"content": "", "detailType": "TEXT"}]

    # img 태그 분할
    img_pattern = re.compile(
        r'<img\s+[^>]*?src=["\']([^"\']+)["\'][^>]*?>', re.IGNORECASE
    )
    segments = img_pattern.split(detail_html)

    # img 태그가 없으면 기존 TEXT 단일 블록
    if len(segments) <= 1:
        return [{"content": detail_html, "detailType": "TEXT"}]

    details: list[dict[str, Any]] = []
    for i, segment in enumerate(segments):
        segment = segment.strip()
        if not segment:
            continue
        if i % 2 == 0:
            # 텍스트 구간
            details.append({"content": segment, "detailType": "TEXT"})
        else:
            # img src URL
            url = segment
            if url.startswith("//"):
                url = "https:" + url
            details.append({"content": url, "detailType": "IMAGE"})

    return details if details else [{"content": detail_html, "detailType": "TEXT"}]


class CoupangClient:
    """쿠팡 Wing API 클라이언트."""

    BASE_URL = "https://api-gateway.coupang.com"

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        vendor_id: str,
    ) -> None:
        self.access_key = access_key
        self.secret_key = secret_key
        self.vendor_id = vendor_id

    # ------------------------------------------------------------------
    # HMAC 서명 생성
    # ------------------------------------------------------------------

    def _generate_signature(
        self, method: str, path: str, query: str = ""
    ) -> tuple[str, str]:
        """HMAC-SHA256 서명 생성. (authorization_header, datetime) 반환."""
        dt = datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")
        # 메시지: datetime + method + path + query (단순 연결, 구분자 없음)
        message = f"{dt}{method}{path}{query}"
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        authorization = (
            f"CEA algorithm=HmacSHA256, access-key={self.access_key}, "
            f"signed-date={dt}, signature={signature}"
        )
        return authorization, dt

    async def _call_api(
        self,
        method: str,
        path: str,
        body: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """공통 API 호출."""
        query = "&".join(f"{k}={v}" for k, v in (params or {}).items() if v)
        authorization, dt = self._generate_signature(method, path, query)

        url = f"{self.BASE_URL}{path}"
        if query:
            url = f"{url}?{query}"

        headers = {
            "Authorization": authorization,
            "Content-Type": "application/json;charset=UTF-8",
            "X-Requested-By": "samba-wave",
        }

        async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
            if method == "GET":
                resp = await client.get(url, headers=headers)
            elif method == "POST":
                resp = await client.post(url, headers=headers, json=body or {})
            elif method == "PUT":
                resp = await client.put(url, headers=headers, json=body or {})
            elif method == "DELETE":
                resp = await client.delete(url, headers=headers)
            else:
                raise ValueError(f"지원하지 않는 HTTP 메서드: {method}")

            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text}

            logger.info(f"[쿠팡] {method} {path} → {resp.status_code}")

            if not resp.is_success:
                msg = (
                    data.get("message", "") or data.get("reason", "") or resp.text[:200]
                )
                raise CoupangApiError(f"HTTP {resp.status_code}: {msg}")

            # 쿠팡 API는 HTTP 200이지만 body에 code=ERROR 반환하는 경우 있음
            if isinstance(data, dict) and data.get("code") == "ERROR":
                msg = data.get("message", "") or "알 수 없는 오류"
                raise CoupangApiError(f"API ERROR: {msg}")

            return data

    # ------------------------------------------------------------------
    # 카테고리 조회
    # ------------------------------------------------------------------

    async def get_categories(self) -> dict[str, Any]:
        """전체 카테고리 조회 (display category 기반)."""
        return await self._call_api(
            "GET",
            "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories",
        )

    async def resolve_category_code(self, category_path: str) -> int:
        """카테고리 경로 문자열 → displayItemCategoryCode 변환.

        카테고리 트리를 조회하여 경로의 마지막 키워드와 가장 잘 매칭되는 리프 노드 반환.
        """
        try:
            result = await self.get_categories()
            root = result.get("data", result) if isinstance(result, dict) else {}
            if not isinstance(root, dict):
                return 0

            # 트리 평탄화: (경로, 코드) 리스트 생성
            def flatten(node: dict, path: str = "") -> list[tuple[str, int]]:
                code = node.get("displayItemCategoryCode", 0)
                name = node.get("name", "")
                current = f"{path} > {name}" if path else name
                entries: list[tuple[str, int]] = []
                children = node.get("child", [])
                if not children and code:
                    entries.append((current, code))
                for c in children:
                    entries.extend(flatten(c, current))
                return entries

            all_cats = flatten(root)

            # 경로에서 키워드 추출 (예: "패션의류 > 남성의류 > 아우터 > 코트" → ["패션의류", "남성의류", ...])
            keywords = [
                k.strip()
                for k in category_path.replace(">", "/").split("/")
                if k.strip()
            ]

            # 가중치 매칭: 상위 카테고리(성별 등)에 높은 가중치 부여
            # 예: ["패션의류", "남성의류", "아우터", "코트"] → 가중치 [4, 3, 2, 1]
            full_matches: list[tuple[str, int, int]] = []
            partial_matches: list[tuple[str, int, int]] = []
            for cat_path, code in all_cats:
                score = 0
                match_count = 0
                for i, kw in enumerate(keywords):
                    if kw in cat_path:
                        score += len(keywords) - i  # 상위 키워드일수록 높은 가중치
                        match_count += 1
                if match_count == len(keywords):
                    full_matches.append((cat_path, code, score))
                elif match_count > 0:
                    partial_matches.append((cat_path, code, score))

            # 전체 매칭 → 가중치 합계 높은 순, 동점이면 경로 짧은 순
            best_code = 0
            if full_matches:
                full_matches.sort(key=lambda x: (-x[2], len(x[0])))
                best_code = full_matches[0][1]
                logger.info(
                    f"[쿠팡] 카테고리 전체매칭: '{category_path}' → {best_code} ({full_matches[0][0]})"
                )
            elif partial_matches:
                partial_matches.sort(key=lambda x: (-x[2], len(x[0])))
                best_code = partial_matches[0][1]
                logger.info(
                    f"[쿠팡] 카테고리 부분매칭: '{category_path}' → {best_code} ({partial_matches[0][0]})"
                )

            if best_code:
                logger.info(f"[쿠팡] 카테고리 매핑: '{category_path}' → {best_code}")
            return best_code
        except Exception as exc:
            logger.warning(f"[쿠팡] 카테고리 코드 조회 실패: {exc}")
            return 0

    async def get_category_by_id(self, category_id: str) -> dict[str, Any]:
        """특정 카테고리 상세 조회."""
        return await self._call_api(
            "GET",
            f"/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories/{category_id}",
        )

    # ------------------------------------------------------------------
    # 상품 등록/수정
    # ------------------------------------------------------------------

    async def register_product(self, product_data: dict[str, Any]) -> dict[str, Any]:
        """상품 등록.

        Coupang Wing API: POST /v2/providers/seller_api/apis/api/v1/marketplace/seller-products
        """
        result = await self._call_api(
            "POST",
            "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products",
            body=product_data,
        )
        return {"success": True, "data": result}

    async def update_product(
        self, seller_product_id: str, product_data: dict[str, Any]
    ) -> dict[str, Any]:
        """상품 수정."""
        result = await self._call_api(
            "PUT",
            f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{seller_product_id}",
            body=product_data,
        )
        return {"success": True, "data": result}

    async def delete_product(self, seller_product_id: str) -> dict[str, Any]:
        """상품 삭제 (리스트에서 완전 제거)."""
        result = await self._call_api(
            "DELETE",
            f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{seller_product_id}",
        )
        return {"success": True, "data": result}

    async def get_product(self, seller_product_id: str) -> dict[str, Any]:
        """상품 조회."""
        return await self._call_api(
            "GET",
            f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{seller_product_id}",
        )

    # ------------------------------------------------------------------
    # 상품 데이터 변환
    # ------------------------------------------------------------------

    @staticmethod
    def transform_product(
        product: dict[str, Any],
        category_id: str = "",
        return_center_code: str = "",
        outbound_shipping_place_code: str = "",
    ) -> dict[str, Any]:
        """SambaCollectedProduct → 쿠팡 상품 등록 데이터 변환.

        쿠팡 Wing API 공식 스펙 기준 전체 필수필드 포함.
        SEO 최적화: 노출상품명 자동생성, 검색태그, 옵션별 색상분리, 상세이미지 분리.
        """
        from datetime import datetime as dt, timezone as tz

        images_raw = product.get("images") or []
        coupang_main = product.get("coupang_main_image") or ""
        default_color = product.get("color", "") or "상세 이미지 참조"
        detail_html = (
            product.get("detail_html", "") or f"<p>{product.get('name', '')}</p>"
        )

        # 카테고리 코드 (숫자만 허용)
        display_category = (
            int(category_id) if category_id and str(category_id).isdigit() else 0
        )

        # 판매기간
        now = dt.now(tz.utc).strftime("%Y-%m-%dT%H:%M:%S")

        # 고시정보 — 카테고리별 동적 생성
        from backend.domain.samba.proxy.notice_utils import build_coupang_notices

        notices = build_coupang_notices(product)

        # 상세 컨텐츠 (IMAGE/TEXT 혼합)
        content_details = _build_content_details(detail_html)

        # 아이템별 공통 필드 생성 함수
        def _build_item(
            item_name: str, stock: int, size_val: str, item_color: str = ""
        ) -> dict[str, Any]:
            # 아이템별 이미지 (대표 + 상세)
            # 쿠팡 전용 대표이미지가 있으면 우선 사용, 없으면 공통 대표(images[0])
            rep_image = coupang_main or (images_raw[0] if images_raw else "")
            item_images: list[dict[str, Any]] = []
            if rep_image:
                item_images.append(
                    {
                        "imageOrder": 0,
                        "imageType": "REPRESENTATION",
                        "vendorPath": rep_image,
                    }
                )
                for idx, url in enumerate(images_raw[1:10], start=1):
                    item_images.append(
                        {
                            "imageOrder": idx,
                            "imageType": "DETAIL",
                            "vendorPath": url,
                        }
                    )

            # 아이템별 색상 (옵션에서 파싱된 개별 색상 우선)
            resolved_color = item_color or default_color

            return {
                "itemName": item_name,
                "originalPrice": int(product.get("original_price", 0)) // 10 * 10,
                "salePrice": int(product.get("sale_price", 0)) // 10 * 10,
                "maximumBuyCount": min(stock, 99999),
                "maximumBuyForPerson": 0,
                "maximumBuyForPersonPeriod": 1,
                "outboundShippingTimeDay": 3,
                "unitCount": 1,
                "adultOnly": "EVERYONE",
                "taxType": "TAX",
                "parallelImported": "NOT_PARALLEL_IMPORTED",
                "overseasPurchased": "NOT_OVERSEAS_PURCHASED",
                "pccNeeded": False,
                "barcode": "",
                "emptyBarcode": True,
                "emptyBarcodeReason": "바코드 없음",
                "offerCondition": "NEW",
                "attributes": [
                    {
                        "attributeTypeName": "패션의류/잡화 사이즈",
                        "attributeValueName": size_val,
                    },
                    {"attributeTypeName": "색상", "attributeValueName": resolved_color},
                ],
                "contents": [
                    {
                        "contentsType": "HTML",
                        "contentDetails": content_details,
                    }
                ],
                "notices": notices,
                "images": item_images,
                "certifications": [
                    {"certificationType": "NOT_REQUIRED", "certificationCode": ""}
                ],
            }

        # 옵션 처리 — 색상/사이즈 분리
        options = product.get("options") or []
        items = []
        if options:
            for opt in options:
                opt_name = opt.get("name", "") or opt.get("size", "") or "기본"
                opt_stock = opt.get("stock", 999)
                opt_color, size_val = _parse_option_color_size(opt_name, default_color)
                items.append(_build_item(opt_name, opt_stock, size_val, opt_color))
        else:
            items.append(
                _build_item(product.get("name", "기본"), 999, "FREE", default_color)
            )

        # SEO 최적화: 노출상품명 + 검색태그
        display_name = _build_display_product_name(product)
        search_tags = _build_search_tags(product)

        result: dict[str, Any] = {
            "displayCategoryCode": display_category,
            "sellerProductName": product.get("name", "")[:100],
            "vendorId": "",  # 런타임에 디스패처에서 채움
            "saleStartedAt": now,
            "saleEndedAt": "2099-01-01T23:59:59",
            "displayProductName": display_name,
            "brand": product.get("brand", ""),
            "generalProductName": display_name,
            "productGroup": "",
            "deliveryMethod": "SEQUENCIAL",
            "deliveryCompanyCode": "CJGLS",
            "deliveryChargeType": "FREE",
            "deliveryCharge": 0,
            "freeShipOverAmount": 0,
            "deliveryChargeOnReturn": 2500,
            "remoteAreaDeliverable": "N",
            "unionDeliveryType": "NOT_UNION_DELIVERY",
            "returnCenterCode": return_center_code or "NO_RETURN_CENTERCODE",
            "returnChargeName": "반품지",
            "companyContactNumber": product.get("_as_phone", "") or "상세페이지 참조",
            "returnZipCode": "00000",
            "returnAddress": "상세페이지 참조",
            "returnAddressDetail": "상세페이지 참조",
            "returnCharge": 2500,
            "outboundShippingPlaceCode": int(outbound_shipping_place_code)
            if outbound_shipping_place_code
            else 0,
            "vendorUserId": "",  # 런타임에 디스패처에서 채움
            "requested": True,
            "items": items,
            "requiredDocuments": [],
            "extraInfoMessage": "",
            "manufacture": product.get("manufacturer", "") or product.get("brand", ""),
        }

        # 검색태그 추가 (쿠팡 API가 지원하면 반영됨)
        if search_tags:
            result["searchTags"] = search_tags

        return result


class CoupangApiError(Exception):
    """쿠팡 API 에러."""

    pass
