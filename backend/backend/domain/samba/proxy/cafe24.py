"""카페24 Admin API 클라이언트 — 상품 등록/수정/삭제 + 카테고리 조회.

인증 방식: OAuth2 Authorization Code Flow
- mallId별 Base URL: https://{mallId}.cafe24api.com/api/v2/admin/
- Access Token 유효기간: 2시간, Refresh Token: 2주
- Rate Limit: Leaky Bucket 40/2초
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from backend.domain.samba.proxy.base_client import BaseProxyClient
from backend.utils.logger import logger


class Cafe24ApiError(Exception):
    """카페24 API 에러."""

    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        super().__init__(f"[{status}] {code}: {message}")


class Cafe24Client(BaseProxyClient):
    """카페24 Admin REST API 클라이언트."""

    timeout = 60.0
    market_name = "카페24"

    def __init__(
        self,
        mall_id: str,
        client_id: str,
        client_secret: str,
        access_token: str = "",
        refresh_token: str = "",
    ):
        super().__init__()
        self.mall_id = mall_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.base_url = f"https://{mall_id}.cafe24api.com/api/v2/admin"

    # ── 인증 ────────────────────────────────────────

    async def ensure_token(self) -> str:
        """Access Token이 없거나 만료 시 Refresh Token으로 갱신."""
        if self.access_token:
            return self.access_token
        if not self.refresh_token:
            raise Cafe24ApiError(
                401, "NO_TOKEN", "access_token과 refresh_token이 모두 없습니다"
            )
        return await self._refresh_access_token()

    async def _refresh_access_token(self) -> str:
        """Refresh Token으로 Access Token 재발급."""
        url = f"https://{self.mall_id}.cafe24api.com/api/v2/oauth/token"
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }
        import base64

        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

        # 토큰 갱신은 별도 클라이언트로 진행 (base_url이 다름)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                data=data,
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
        body = resp.json()
        if resp.status_code != 200:
            raise Cafe24ApiError(
                resp.status_code,
                body.get("error", "TOKEN_ERROR"),
                body.get("error_description", "토큰 갱신 실패"),
            )
        self.access_token = body["access_token"]
        self.refresh_token = body.get("refresh_token", self.refresh_token)
        logger.info(f"[카페24] 토큰 갱신 성공: mall={self.mall_id}")
        return self.access_token

    # ── BaseProxyClient 오버라이드 ──────────────────

    async def _build_headers(self, method: str, path: str) -> dict[str, str]:
        """OAuth2 Bearer 토큰 인증 헤더 생성."""
        token = await self.ensure_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Cafe24-Api-Version": "2024-06-01",
        }

    async def _check_error(self, resp: httpx.Response, data: dict[str, Any]) -> None:
        """카페24 에러 포맷 처리 + Rate Limit(429) + 토큰 만료(401) 대응."""
        # Rate Limit 모니터링
        call_limit = resp.headers.get("X-Api-Call-Limit", "")
        remaining = resp.headers.get("x-ratelimit-remaining", "")
        if call_limit:
            logger.debug(f"[카페24] Rate: {call_limit}, remaining={remaining}")

        if resp.status_code >= 400:
            error = data.get("error", {}) if isinstance(data.get("error"), dict) else {}
            raise Cafe24ApiError(
                resp.status_code,
                error.get("code", str(resp.status_code)),
                error.get("message", data.get("error_description", str(data))),
            )

    # ── 공통 API 호출 (Rate Limit + 토큰 갱신 재시도) ──

    async def _call_api(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        params: dict | None = None,
        retry_on_token: bool = True,
    ) -> dict[str, Any]:
        """공통 API 호출 — Rate Limit 대응 + 토큰 자동 갱신."""
        try:
            return await super()._call_api(method, path, body=body, params=params)
        except Cafe24ApiError as exc:
            # 429 Too Many Requests → 대기 후 재시도
            if exc.status == 429:
                logger.warning("[카페24] Rate Limit 초과 → 2초 대기 후 재시도")
                await asyncio.sleep(2)
                return await super()._call_api(method, path, body=body, params=params)

            # 401 → 토큰 갱신 후 재시도 (1회만)
            if exc.status == 401 and retry_on_token and self.refresh_token:
                logger.info("[카페24] 401 → 토큰 갱신 후 재시도")
                self.access_token = ""
                await self.ensure_token()
                return await super()._call_api(method, path, body=body, params=params)

            raise

    # ── 카테고리 ────────────────────────────────────

    async def get_categories(self, shop_no: int = 1) -> list[dict[str, Any]]:
        """카테고리 전체 목록 조회 (트리 구조)."""
        result: list[dict[str, Any]] = []
        offset = 0
        limit = 100
        while True:
            data = await self._call_api(
                "GET",
                "/categories",
                params={"shop_no": shop_no, "limit": limit, "offset": offset},
            )
            cats = data.get("categories", [])
            result.extend(cats)
            if len(cats) < limit:
                break
            offset += limit
        return result

    async def link_product_to_category(
        self,
        product_no: int,
        category_no: int,
        shop_no: int = 1,
    ) -> dict[str, Any]:
        """상품을 카테고리에 연결."""
        return await self._call_api(
            "POST",
            "/categories/products",
            body={
                "shop_no": shop_no,
                "request": {
                    "product_no": product_no,
                    "category_no": category_no,
                },
            },
        )

    # ── 상품 CRUD ──────────────────────────────────

    async def register_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        """상품 신규 등록."""
        data = await self._call_api("POST", "/products", body=payload)
        product = data.get("product", {})
        product_no = product.get("product_no")
        logger.info(f"[카페24] 상품 등록 성공: product_no={product_no}")
        return product

    async def update_product(
        self, product_no: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """상품 수정."""
        data = await self._call_api("PUT", f"/products/{product_no}", body=payload)
        logger.info(f"[카페24] 상품 수정 성공: product_no={product_no}")
        return data.get("product", {})

    async def delete_product(self, product_no: int) -> dict[str, Any]:
        """상품 삭제 (마켓에서 완전 삭제)."""
        data = await self._call_api("DELETE", f"/products/{product_no}")
        logger.info(f"[카페24] 상품 삭제 성공: product_no={product_no}")
        return data

    async def get_product(self, product_no: int) -> dict[str, Any]:
        """상품 상세 조회."""
        data = await self._call_api("GET", f"/products/{product_no}")
        return data.get("product", {})

    # ── 이미지 업로드 ──────────────────────────────

    async def upload_images(
        self,
        product_no: int,
        image_urls: list[str],
    ) -> dict[str, Any]:
        """상품 이미지 등록 (URL 기반).

        카페24는 이미지 URL을 직접 받아 서버에서 다운로드.
        detail_image(1~10): 메인 이미지, list_image(1~5): 목록 이미지
        """
        request_body: dict[str, Any] = {}
        for i, url in enumerate(image_urls[:10]):
            if url.startswith("//"):
                url = "https:" + url
            request_body[f"detail_image{i + 1}"] = url
            # 첫 번째 이미지를 목록 이미지로도 등록
            if i < 5:
                request_body[f"list_image{i + 1}"] = url

        return await self._call_api(
            "PUT",
            f"/products/{product_no}",
            body={"shop_no": 1, "request": request_body},
        )

    # ── 옵션 / Variants ────────────────────────────

    async def register_options(
        self,
        product_no: int,
        options: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """상품 옵션 등록.

        options: [{"name": "색상", "values": ["빨강", "파랑"]}, ...]
        """
        option_list = []
        for opt in options:
            option_list.append(
                {
                    "option_name": opt["name"],
                    "option_value": opt["values"],
                }
            )
        return await self._call_api(
            "POST",
            f"/products/{product_no}/options",
            body={"shop_no": 1, "request": {"options": option_list}},
        )

    async def get_variants(self, product_no: int) -> list[dict[str, Any]]:
        """품목(variant) 목록 조회."""
        data = await self._call_api("GET", f"/products/{product_no}/variants")
        return data.get("variants", [])

    async def update_variant(
        self,
        product_no: int,
        variant_code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """품목별 가격/재고 수정."""
        return await self._call_api(
            "PUT",
            f"/products/{product_no}/variants/{variant_code}",
            body={"shop_no": 1, "request": payload},
        )

    # ── 판매중지/재개 ──────────────────────────────

    async def stop_selling(self, product_no: int) -> dict[str, Any]:
        """판매중지 (display=F, selling=F)."""
        return await self.update_product(
            product_no,
            {
                "shop_no": 1,
                "request": {"display": "F", "selling": "F"},
            },
        )

    async def resume_selling(self, product_no: int) -> dict[str, Any]:
        """판매재개 (display=T, selling=T)."""
        return await self.update_product(
            product_no,
            {
                "shop_no": 1,
                "request": {"display": "T", "selling": "T"},
            },
        )

    # ── 상품 데이터 변환 ──────────────────────────

    @staticmethod
    def transform_product(
        product: dict[str, Any],
        category_id: str = "",
    ) -> dict[str, Any]:
        """SambaCollectedProduct → 카페24 상품 등록 포맷 변환."""

        # 가격 계산
        sale_price = int(product.get("sale_price", 0) or 0)
        original_price = int(product.get("original_price", 0) or 0)
        if sale_price <= 0:
            sale_price = original_price or 10000
        # 10원 단위 올림
        sale_price = ((sale_price + 9) // 10) * 10

        # 정가(비교가): 원래가격이 판매가보다 높으면 표시
        retail_price = original_price if original_price > sale_price else 0
        if retail_price:
            retail_price = ((retail_price + 9) // 10) * 10

        # 상품명 (최대 250자)
        name = (product.get("name") or "상품명 없음")[:250]

        # 상세설명 HTML
        detail_html = product.get("detail_html", "") or ""
        # 프로토콜 없는 이미지 URL 보정
        if detail_html:
            detail_html = re.sub(r'(src=["\'])\/\/', r"\1https://", detail_html)

        # 요약 설명 (255자)
        summary = ""
        brand = product.get("brand", "")
        if brand:
            summary = f"[{brand}] {name}"[:255]

        # 이미지 URL 수집
        images = product.get("images") or []
        image_fields: dict[str, str] = {}
        for i, url in enumerate(images[:10]):
            if url.startswith("//"):
                url = "https:" + url
            image_fields[f"detail_image{i + 1}"] = url
            if i < 5:
                image_fields[f"list_image{i + 1}"] = url

        # 옵션 처리
        options = product.get("options") or []
        has_option = "T" if options else "F"

        # 재고: 옵션 합산 또는 정책 제한
        max_stock = product.get("_max_stock", 0)
        if options:
            total_stock = sum(
                (o.get("stock") or 0) for o in options if not o.get("isSoldOut")
            )
        else:
            total_stock = 999
        if max_stock and max_stock > 0:
            total_stock = min(max_stock, total_stock) if total_stock > 0 else max_stock
        if total_stock <= 0:
            total_stock = 0

        # 배송비
        delivery_fee_type = product.get("_delivery_fee_type", "")
        delivery_base_fee = product.get("_delivery_base_fee", 0)
        # 카페24: shipping_fee_type — A(무료), B(유료), C(조건부무료)
        if delivery_fee_type == "PAID" and delivery_base_fee > 0:
            shipping_type = "B"
            shipping_fee = delivery_base_fee
        else:
            shipping_type = "A"
            shipping_fee = 0

        # 상품 상태
        product_condition = "N"  # 신상품

        # 사용자 정의 코드 (소싱처 상품코드)
        custom_code = (product.get("source_product_id") or product.get("id", ""))[:40]

        request_body: dict[str, Any] = {
            "product_name": name,
            "display": "T",
            "selling": "T",
            "product_condition": product_condition,
            "price": sale_price,
            "supply_price": sale_price,
            "has_option": has_option,
            "description": detail_html,
            "custom_product_code": custom_code,
            "summary_description": summary,
            "shipping_fee_type": shipping_type,
            **image_fields,
        }

        if retail_price:
            request_body["retail_price"] = retail_price
        if shipping_fee:
            request_body["shipping_fee"] = shipping_fee

        return {"shop_no": 1, "request": request_body}

    @staticmethod
    def build_options_payload(
        options: list[dict[str, Any]],
        sale_price: int,
        max_stock_per_option: int = 0,
    ) -> list[dict[str, Any]] | None:
        """수집 옵션 → 카페24 옵션 등록 포맷 변환.

        카페24 옵션 구조:
        - 옵션명/값 등록 → variants 자동 생성 → variant별 가격/재고 설정
        """
        if not options:
            return None

        # 옵션명에 "/" 포함 → 2단 옵션 (색상/사이즈)
        has_slash = any("/" in (o.get("name") or "") for o in options)

        if has_slash:
            # 2단 옵션: 색상, 사이즈 분리
            colors: list[str] = []
            sizes: list[str] = []
            for o in options:
                name = o.get("name") or o.get("size") or ""
                if "/" in name:
                    parts = [p.strip() for p in name.split("/", 1)]
                    if parts[0] and parts[0] not in colors:
                        colors.append(parts[0])
                    if len(parts) > 1 and parts[1] and parts[1] not in sizes:
                        sizes.append(parts[1])

            result = []
            if colors:
                result.append({"name": "색상", "values": colors})
            if sizes:
                result.append({"name": "사이즈", "values": sizes})
            return result if result else None
        else:
            # 1단 옵션: 사이즈
            values = []
            for o in options:
                name = o.get("name") or o.get("size") or ""
                if name and name not in values:
                    values.append(name)
            return [{"name": "사이즈", "values": values}] if values else None

    @staticmethod
    def build_variant_updates(
        options: list[dict[str, Any]],
        variants: list[dict[str, Any]],
        sale_price: int,
        max_stock: int = 0,
    ) -> list[dict[str, Any]]:
        """수집 옵션 데이터 → 카페24 variant별 가격/재고 업데이트 목록.

        variants: get_variants() 결과
        반환: [{"variant_code": "...", "quantity": N, "price": N}, ...]
        """
        # 옵션명 → 재고/가격 매핑
        opt_map: dict[str, dict[str, Any]] = {}
        for o in options:
            name = (o.get("name") or o.get("size") or "").strip()
            if name:
                opt_map[name] = {
                    "stock": o.get("stock", 0) or 0,
                    "sold_out": o.get("isSoldOut", False),
                    "price": int(o.get("price", 0) or 0),
                }

        updates = []
        for v in variants:
            vcode = v.get("variant_code", "")
            # variant의 옵션값 조합으로 매칭
            option_values = []
            for i in range(1, 6):
                val = v.get(f"option_value{i}", "")
                if val:
                    option_values.append(val)
            option_key = (
                " / ".join(option_values)
                if len(option_values) > 1
                else (option_values[0] if option_values else "")
            )

            matched = opt_map.get(option_key)
            if matched:
                stock = 0 if matched["sold_out"] else matched["stock"]
                if max_stock and max_stock > 0:
                    stock = min(stock, max_stock)
                updates.append(
                    {
                        "variant_code": vcode,
                        "quantity": max(stock, 0),
                    }
                )
            else:
                # 매칭 안 되면 기본 재고 설정
                default_stock = max_stock if max_stock > 0 else 10
                updates.append(
                    {
                        "variant_code": vcode,
                        "quantity": default_stock,
                    }
                )

        return updates
