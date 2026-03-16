"""KREAM 리셀 플랫폼 API 클라이언트 - httpx 기반.

proxy-server.mjs의 KREAM 관련 로직을 Python으로 포팅.
상품 검색, 상세 조회, 시세 조회, 매도 입찰(등록/수정/취소) 등을 지원한다.

주의: KREAM 상품 상세/검색은 확장앱 큐 방식이 원본이므로,
여기서는 API 직접 호출이 가능한 엔드포인트만 포팅하고
확장앱 큐 방식은 라우터 레벨에서 처리한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from backend.utils.logger import logger


class KreamClient:
    """KREAM API 클라이언트 (검색, 상세, 시세, 매도 입찰)."""

    BASE = "https://kream.co.kr"
    API_BASE = "https://kream.co.kr/api"

    HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://kream.co.kr/",
        "Origin": "https://kream.co.kr",
    }

    def __init__(self, token: str = "", cookie: str = "") -> None:
        self.token = token
        self.cookie = cookie

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self, extra: Optional[dict[str, str]] = None) -> dict[str, str]:
        h = {**self.HEADERS}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if self.cookie:
            h["Cookie"] = self.cookie
        if extra:
            h.update(extra)
        return h

    @staticmethod
    def transform_to_product(item: dict[str, Any]) -> dict[str, Any]:
        """KREAM 상품 데이터를 표준 스키마로 변환.

        proxy-server.mjs ``transformKreamToProduct()`` 포팅.
        """
        product_id = str(
            item.get("id") or item.get("product_id") or item.get("productId", "")
        )
        sizes = (
            item.get("sales_options")
            or item.get("sizes")
            or item.get("product_options")
            or item.get("options")
            or []
        )

        options = []
        for s in sizes:
            name = (
                s.get("option")
                or s.get("size")
                or s.get("name")
                or s.get("option_name", "")
            )
            ask = (
                s.get("buy_now_price")
                or s.get("immediate_purchase_price")
                or s.get("ask")
                or s.get("immediate_buy_price")
                or s.get("price")
                or 0
            )
            bid = s.get("sell_now_price") or s.get("immediate_sell_price") or s.get("bid", 0)
            last_sale = s.get("last_sale_price") or s.get("last_price", 0)

            if name:
                options.append(
                    {
                        "name": name,
                        "price": ask,
                        "stock": 0 if (s.get("is_sold_out") or ask == 0) else 1,
                        "isSoldOut": s.get("is_sold_out", False),
                        "kreamFastPrice": 0,
                        "kreamNormalPrice": 0,
                        "kreamAsk": ask,
                        "kreamBid": bid,
                        "kreamLastSale": last_sale,
                    }
                )

        # 최소 ask 가격
        ask_prices = [o["kreamAsk"] for o in options if o["kreamAsk"] > 0]
        min_ask = min(ask_prices) if ask_prices else 0
        sale_price = min_ask if min_ask > 0 else (item.get("retail_price", 0) or 0)

        brand_name = (item.get("brand") or {}).get("name", "") if isinstance(
            item.get("brand"), dict
        ) else (item.get("brand_name", ""))

        product_name = item.get("name") or item.get("translated_name", "")
        if brand_name and product_name.startswith(f"{brand_name} "):
            product_name = product_name[len(brand_name) + 1 :]

        raw_img = item.get("thumbnail_url") or item.get("image_url", "")
        category_str = item.get("category", "")
        category_parts = [
            c.strip() for c in category_str.split(">") if c.strip()
        ] if category_str else []

        now_iso = datetime.now(tz=timezone.utc).isoformat()
        today_str = now_iso[:10]

        return {
            "id": f"col_kream_{product_id}_{int(datetime.now(tz=timezone.utc).timestamp() * 1000)}",
            "sourceSite": "KREAM",
            "siteProductId": product_id,
            "sourceUrl": f"https://kream.co.kr/products/{product_id}",
            "name": product_name,
            "brand": brand_name,
            "category": category_str,
            "category1": category_parts[0] if len(category_parts) > 0 else "",
            "category2": category_parts[1] if len(category_parts) > 1 else "",
            "category3": category_parts[2] if len(category_parts) > 2 else "",
            "category4": category_parts[3] if len(category_parts) > 3 else "",
            "images": [raw_img] if raw_img else [],
            "detailImages": [],
            "detailHtml": "",
            "options": options,
            "originalPrice": item.get("retail_price", 0) or 0,
            "salePrice": sale_price,
            "discountRate": 0,
            "styleCode": item.get("style_code") or item.get("model_no", ""),
            "origin": "",
            "material": "",
            "season": "",
            "status": "collected",
            "appliedPolicyId": None,
            "marketPrices": {},
            "updateEnabled": True,
            "priceUpdateEnabled": True,
            "stockUpdateEnabled": True,
            "marketTransmitEnabled": True,
            "registeredAccounts": [],
            "kreamData": {
                "modelNo": item.get("style_code") or item.get("model_no", ""),
                "releaseDate": item.get("release_date", ""),
                "retailPrice": item.get("retail_price", 0) or 0,
                "askPrices": {
                    o["name"]: {
                        "fast": o.get("kreamFastPrice", 0),
                        "normal": o.get("kreamNormalPrice", 0),
                        "general": o["kreamAsk"],
                    }
                    for o in options
                },
                "bidPrices": {
                    o["name"]: {"general": o["kreamBid"]} for o in options
                },
                "lastSalePrices": {
                    o["name"]: {"price": o["kreamLastSale"], "date": today_str}
                    for o in options
                },
                "tradeVolume": item.get("trade_count") or item.get("total_trades", 0),
                "wishCount": item.get("wish_count") or item.get("wishlist_count", 0),
                "saleTypes": {"general": True, "storage": False, "grade95": False},
                "fetchedAt": now_iso,
            },
            "collectedAt": now_iso,
            "updatedAt": now_iso,
        }

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def login(self, email: str, password: str) -> dict[str, Any]:
        """KREAM 로그인 - proxy-server.mjs /api/kream/login 포팅."""
        timeout = httpx.Timeout(15.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            # 첫 번째 시도: /api/session
            try:
                resp = await client.post(
                    f"{self.BASE}/api/session",
                    json={"email": email, "password": password},
                    headers={
                        "Content-Type": "application/json",
                        **self.HEADERS,
                        "Referer": "https://kream.co.kr/login",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    token = (
                        data.get("access_token")
                        or data.get("token")
                        or (data.get("data") or {}).get("token", "")
                    )
                    if token:
                        self.token = token
                        user_id = (
                            (data.get("user") or {}).get("id")
                            or (data.get("data") or {}).get("user_id", "")
                        )
                        return {
                            "success": True,
                            "isLoggedIn": True,
                            "userId": str(user_id),
                            "message": "KREAM 로그인 성공",
                        }
            except Exception:
                pass

            # 두 번째 시도: /auth/login
            resp2 = await client.post(
                f"{self.BASE}/auth/login",
                json={"email": email, "password": password},
                headers={
                    "Content-Type": "application/json",
                    "Referer": "https://kream.co.kr/login",
                    "Origin": "https://kream.co.kr",
                },
            )
            if resp2.status_code != 200:
                return {
                    "success": False,
                    "message": f"KREAM 로그인 실패: HTTP {resp2.status_code}",
                }
            data2 = resp2.json()
            token2 = (
                data2.get("access_token")
                or data2.get("token")
                or (data2.get("data") or {}).get("token", "")
            )
            if not token2:
                return {"success": False, "message": "KREAM 토큰 획득 실패"}

            self.token = token2
            user_id2 = (
                (data2.get("user") or {}).get("id")
                or (data2.get("data") or {}).get("user_id", "")
            )
            return {
                "success": True,
                "isLoggedIn": True,
                "userId": str(user_id2),
                "message": "KREAM 로그인 성공",
            }

    async def check_auth_status(self) -> dict[str, Any]:
        """인증 상태 확인 - proxy-server.mjs /api/kream/auth/status 포팅."""
        if not self.token:
            return {"isLoggedIn": False}

        timeout = httpx.Timeout(10.0, connect=5.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(
                    f"{self.API_BASE}/users/me",
                    headers=self._headers(),
                )
                if resp.status_code != 200:
                    self.token = ""
                    return {"isLoggedIn": False}
                me_data = resp.json()
                user_id = me_data.get("id") or (me_data.get("data") or {}).get("id", "")
                return {"isLoggedIn": True, "userId": str(user_id), "message": "로그인 상태"}
        except Exception:
            return {"isLoggedIn": bool(self.token)}

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------

    async def get_prices(self, product_id: str) -> dict[str, Any]:
        """사이즈별 시세 조회 - proxy-server.mjs /api/kream/products/:id/prices 포팅."""
        if not self.cookie:
            return {"success": False, "message": "KREAM 쿠키가 없습니다."}

        timeout = httpx.Timeout(15.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                f"{self.API_BASE}/products/{product_id}/prices",
                headers={
                    "Cookie": self.cookie,
                    "Referer": f"https://kream.co.kr/products/{product_id}",
                    "User-Agent": self.HEADERS["User-Agent"],
                },
            )
            if resp.status_code != 200:
                return {
                    "success": False,
                    "message": f"KREAM API 오류: {resp.status_code}",
                }
            prices_data = resp.json()
            return {
                "success": True,
                "data": prices_data.get("data") or prices_data,
            }

    # ------------------------------------------------------------------
    # Sell (매도 입찰)
    # ------------------------------------------------------------------

    async def create_ask(
        self,
        product_id: str,
        size: str,
        price: int,
        sale_type: str = "general",
    ) -> dict[str, Any]:
        """매도 입찰 등록 - proxy-server.mjs /api/kream/sell/bid 포팅."""
        if not self.token:
            return {"success": False, "message": "KREAM 로그인이 필요합니다."}

        timeout = httpx.Timeout(15.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{self.API_BASE}/asks",
                json={
                    "product_id": product_id,
                    "size": size,
                    "price": price,
                    "sale_type": sale_type,
                },
                headers=self._headers({"Content-Type": "application/json"}),
            )
            if resp.status_code not in (200, 201):
                err_data = {}
                try:
                    err_data = resp.json()
                except Exception:
                    pass
                return {
                    "success": False,
                    "message": (
                        err_data.get("message")
                        or f"매도 입찰 실패: {resp.status_code}"
                    ),
                }
            bid_data = resp.json()
            logger.info(
                f"[KREAM] 매도 입찰 등록: {product_id} / {size} / {price:,}원"
            )
            return {
                "success": True,
                "data": bid_data.get("data") or bid_data,
                "message": "매도 입찰 등록 완료",
            }

    async def update_ask(self, ask_id: str, price: int) -> dict[str, Any]:
        """매도 입찰 수정 - proxy-server.mjs PUT /api/kream/sell/bid/:id 포팅."""
        if not self.token:
            return {"success": False, "message": "KREAM 로그인이 필요합니다."}

        timeout = httpx.Timeout(15.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.put(
                f"{self.API_BASE}/asks/{ask_id}",
                json={"price": price},
                headers=self._headers({"Content-Type": "application/json"}),
            )
            try:
                data = resp.json()
            except Exception:
                data = {}
            return {
                "success": resp.status_code in (200, 201),
                "data": data.get("data") or data,
            }

    async def cancel_ask(self, ask_id: str) -> dict[str, Any]:
        """매도 입찰 취소 - proxy-server.mjs DELETE /api/kream/sell/bid/:id 포팅."""
        if not self.token:
            return {"success": False, "message": "KREAM 로그인이 필요합니다."}

        timeout = httpx.Timeout(15.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.delete(
                f"{self.API_BASE}/asks/{ask_id}",
                headers=self._headers(),
            )
            return {
                "success": resp.status_code in (200, 204),
                "message": "매도 입찰 취소 완료" if resp.status_code in (200, 204) else "취소 실패",
            }

    async def get_my_asks(self) -> dict[str, Any]:
        """내 매도 입찰 목록 - proxy-server.mjs /api/kream/sell/my-bids 포팅."""
        if not self.token:
            return {"success": False, "message": "KREAM 로그인이 필요합니다."}

        timeout = httpx.Timeout(15.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                f"{self.API_BASE}/asks/me",
                headers=self._headers(),
            )
            if resp.status_code != 200:
                return {
                    "success": False,
                    "message": f"조회 실패: {resp.status_code}",
                }
            data = resp.json()
            return {"success": True, "data": data.get("data") or data}

    # ------------------------------------------------------------------
    # Image proxy
    # ------------------------------------------------------------------

    @staticmethod
    async def proxy_image(url: str) -> tuple[bytes, str]:
        """이미지 프록시 - KREAM 이미지 CORS 우회.

        Returns (image_bytes, content_type).
        """
        timeout = httpx.Timeout(15.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                url,
                headers={
                    "Referer": "https://kream.co.kr/",
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                },
            )
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "image/jpeg")
            return resp.content, content_type
