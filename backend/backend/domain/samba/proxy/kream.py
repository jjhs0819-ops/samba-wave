"""KREAM 리셀 플랫폼 API 클라이언트 - httpx 기반.

proxy-server.mjs의 KREAM 관련 로직을 Python으로 포팅.
상품 검색, 상세 조회, 시세 조회, 매도 입찰(등록/수정/취소) 등을 지원한다.

주의: KREAM 상품 상세/검색은 확장앱 큐 방식이 원본이므로,
여기서는 API 직접 호출이 가능한 엔드포인트만 포팅하고
확장앱 큐 방식은 라우터 레벨에서 처리한다.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

import httpx

from backend.utils.logger import logger


class KreamClient:
    """KREAM API 클라이언트 (검색, 상세, 시세, 매도 입찰).

    검색/상세는 확장앱 큐 방식으로 동작한다.
    확장앱이 큐를 폴링 → 브라우저에서 KREAM 페이지를 열어 데이터 추출 → 결과 전달.
    """

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

    # ── 확장앱 큐 (클래스 레벨, 서버 재시작 시 초기화) ──
    collect_queue: list[dict[str, Any]] = []
    collect_resolvers: dict[str, asyncio.Future[Any]] = {}
    search_queue: list[dict[str, Any]] = []
    search_resolvers: dict[str, asyncio.Future[Any]] = {}

    @classmethod
    def cancel_all(cls, reason: str = "server is shutting down") -> None:
        cls.collect_queue.clear()
        cls.search_queue.clear()
        pending = [
            *cls.collect_resolvers.items(),
            *cls.search_resolvers.items(),
        ]
        cls.collect_resolvers.clear()
        cls.search_resolvers.clear()
        for request_id, future in pending:
            if future.done():
                continue
            exc = RuntimeError(reason)
            try:
                loop = future.get_loop()
                loop.call_soon_threadsafe(future.set_exception, exc)
            except RuntimeError:
                if not future.done():
                    future.set_exception(exc)
            logger.info(f"[KREAM] shutdown cancel: {request_id}")

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
            bid = (
                s.get("sell_now_price")
                or s.get("immediate_sell_price")
                or s.get("bid", 0)
            )
            last_sale = s.get("last_sale_price") or s.get("last_price", 0)

            if name:
                options.append(
                    {
                        "name": name,
                        "price": ask,
                        "stock": 0 if (s.get("is_sold_out") or ask == 0) else 99,
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

        brand_name = (
            (item.get("brand") or {}).get("name", "")
            if isinstance(item.get("brand"), dict)
            else (item.get("brand_name", ""))
        )

        product_name = item.get("name") or item.get("translated_name", "")
        if brand_name and product_name.startswith(f"{brand_name} "):
            product_name = product_name[len(brand_name) + 1 :]

        raw_img = item.get("thumbnail_url") or item.get("image_url", "")
        category_str = item.get("category", "")
        category_parts = (
            [c.strip() for c in category_str.split(">") if c.strip()]
            if category_str
            else []
        )

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
            # 공통 컬럼 (소싱처 공통)
            "style_code": item.get("style_code") or item.get("model_no", ""),
            "sex": (lambda s: "남녀공용" if len(s) > 1 else (s[0] if s else ""))(
                item.get("sex") or []
            ),
            "season": item.get("season", ""),
            "origin": "",
            "material": "",
            "care_instructions": "",
            "quality_guarantee": "",
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
                "bidPrices": {o["name"]: {"general": o["kreamBid"]} for o in options},
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
                        user_id = (data.get("user") or {}).get("id") or (
                            data.get("data") or {}
                        ).get("user_id", "")
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
            user_id2 = (data2.get("user") or {}).get("id") or (
                data2.get("data") or {}
            ).get("user_id", "")
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
                return {
                    "isLoggedIn": True,
                    "userId": str(user_id),
                    "message": "로그인 상태",
                }
        except Exception:
            return {"isLoggedIn": bool(self.token)}

    # ------------------------------------------------------------------
    # 카테고리 스캔
    # ------------------------------------------------------------------

    async def scan_categories(self, keyword: str) -> dict[str, Any]:
        """KREAM 카테고리 스캔 — 검색 페이지 HTML에서 카테고리 분포 집계.

        검색 결과 HTML의 __NUXT__ 데이터에 포함된
        shop_category_name_1d(대분류), shop_category_name_2d(중분류)를 추출한다.
        단일 HTTP 요청으로 최대 100개 상품의 카테고리 분포를 파악할 수 있다.
        """
        import re as _re

        search_url = f"https://kream.co.kr/search?keyword={quote(keyword)}&tab=products"
        timeout = httpx.Timeout(30.0, connect=15.0)

        logger.info(f'[KREAM] 카테고리 스캔 시작: "{keyword}"')

        try:
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=True
            ) as client:
                resp = await client.get(
                    search_url,
                    headers={
                        "User-Agent": self.HEADERS["User-Agent"],
                        "Accept": "text/html,application/xhtml+xml",
                        "Accept-Language": "ko-KR,ko;q=0.9",
                    },
                )
                if resp.status_code != 200:
                    logger.warning(
                        f"[KREAM] 검색 페이지 요청 실패: HTTP {resp.status_code}"
                    )
                    return {"categories": [], "total": 0, "groupCount": 0}
        except Exception as exc:
            logger.error(f"[KREAM] 카테고리 스캔 HTTP 오류: {exc}")
            return {"categories": [], "total": 0, "groupCount": 0}

        text = resp.text
        if not text or len(text) < 10000:
            logger.warning("[KREAM] 검색 페이지 응답이 너무 짧음 (차단 의심)")
            return {"categories": [], "total": 0, "groupCount": 0}

        # __NUXT__ 데이터에서 shop_category_name_1d / 2d 쌍 추출
        # 패턴 1: 이스케이프된 JSON — \"shop_category_name_1d\":\"신발\"
        # 패턴 2: 비이스케이프 JSON — "shop_category_name_1d":"신발"
        cat_pattern_escaped = _re.compile(
            r'shop_category_name_1d\\"+:\\"+([^\\"]+)\\"+,\\"+'
            r'shop_category_name_2d\\"+:\\"+([^\\"]+)'
        )
        matches = cat_pattern_escaped.findall(text)

        if not matches:
            # 폴백: 이스케이프 없는 일반 JSON 패턴
            cat_pattern_raw = _re.compile(
                r'"shop_category_name_1d"\s*:\s*"([^"]+)"\s*,'
                r'\s*"shop_category_name_2d"\s*:\s*"([^"]+)"'
            )
            matches = cat_pattern_raw.findall(text)

        if not matches:
            logger.info(f'[KREAM] 카테고리 데이터 없음: "{keyword}"')
            return {"categories": [], "total": 0, "groupCount": 0}

        # 카테고리별 상품 수 집계
        cat_counter: dict[str, int] = {}
        for c1, c2 in matches:
            path = f"{c1} > {c2}"
            cat_counter[path] = cat_counter.get(path, 0) + 1

        # 상품 수 내림차순 정렬
        categories = []
        for path, count in sorted(cat_counter.items(), key=lambda x: -x[1]):
            parts = path.split(" > ")
            c1 = parts[0] if len(parts) > 0 else ""
            c2 = parts[1] if len(parts) > 1 else ""
            code = f"{c1}_{c2}" if c2 else c1
            categories.append(
                {
                    "categoryCode": code,
                    "path": path,
                    "count": count,
                    "category1": c1,
                    "category2": c2,
                    "category3": "",
                }
            )

        total = sum(c["count"] for c in categories)
        logger.info(
            f'[KREAM] 카테고리 스캔 완료: "{keyword}" → '
            f"{len(categories)}개 카테고리, {total}건"
        )
        return {
            "categories": categories,
            "total": total,
            "groupCount": len(categories),
        }

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------

    async def search(self, keyword: str, size: int = 50) -> list[dict[str, Any]]:
        """KREAM 상품 검색 — SSR HTML 파싱 방식 (확장앱 불필요).

        KREAM 검색 페이지를 직접 HTTP GET → HTML에서 상품 데이터를 추출한다.
        """
        import re as _re
        import html as _html

        search_url = f"https://kream.co.kr/search?keyword={quote(keyword)}&tab=products"
        timeout = httpx.Timeout(20.0, connect=10.0)

        logger.info(f'[KREAM] 검색 시작 (HTTP 파싱): "{keyword}"')

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(
                search_url,
                headers={
                    "User-Agent": self.HEADERS["User-Agent"],
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "ko-KR,ko;q=0.9",
                },
            )
            if resp.status_code != 200:
                raise Exception(f"KREAM 검색 페이지 요청 실패: HTTP {resp.status_code}")

        text = resp.text
        products: list[dict[str, Any]] = []
        seen: set[str] = set()

        # <a href="/products/ID"> 블록에서 상품 정보 추출
        pattern = r'<a[^>]*href="/products/(\d+)"[^>]*>(.*?)</a>'
        matches = _re.findall(pattern, text, _re.DOTALL)

        for pid, content in matches:
            if pid in seen:
                continue
            seen.add(pid)

            # 텍스트 노드 추출
            texts = _re.findall(r">([^<]+)<", content)
            texts = [t.strip() for t in texts if t.strip() and len(t.strip()) > 1]

            # 이미지 추출
            img_match = _re.search(r'<img[^>]+src="([^"]+)"', content)
            raw_img = img_match.group(1).split("?")[0] if img_match else ""

            # 브랜드/상품명
            brand = _html.unescape(texts[0]) if texts else ""
            name = _html.unescape(texts[1]) if len(texts) > 1 else brand

            # 가격 (숫자+원 또는 순수 숫자)
            price = 0
            for t in texts:
                if "원" in t or (_re.match(r"^[\d,]+$", t) and len(t) > 3):
                    price = int(_re.sub(r"[^\d]", "", t))
                    break

            products.append(
                {
                    "id": pid,
                    "siteProductId": pid,
                    "name": name,
                    "brand": brand,
                    "salePrice": price,
                    "originalPrice": 0,
                    "retailPrice": 0,
                    "images": [raw_img] if raw_img else [],
                    "imageUrl": raw_img,
                    "sourceUrl": f"https://kream.co.kr/products/{pid}",
                }
            )

        logger.info(f'[KREAM] 검색 완료: "{keyword}" → {len(products)}개')
        return products

    async def search_via_extension(self, keyword: str) -> list[dict[str, Any]]:
        """KREAM 상품 검색 (확장앱 큐 방식, 최대 90초 대기).

        브라우저 확장앱이 실제 KREAM 검색 페이지를 열어 결과를 스크래핑한다.
        SSR 파싱이 불가능한 경우 fallback으로 사용.
        """
        request_id = str(uuid.uuid4())
        search_url = f"https://kream.co.kr/search?keyword={quote(keyword)}"

        KreamClient.search_queue.append(
            {"requestId": request_id, "keyword": keyword, "url": search_url}
        )
        logger.info(f'[KREAM] 검색 큐 등록 (확장앱): "{keyword}" ({request_id})')

        loop = asyncio.get_event_loop()
        future: asyncio.Future[Any] = loop.create_future()
        KreamClient.search_resolvers[request_id] = future

        try:
            result = await asyncio.wait_for(future, timeout=90.0)
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                return result.get("items", result.get("data", []))
            return []
        except asyncio.TimeoutError:
            KreamClient.search_resolvers.pop(request_id, None)
            raise Exception(
                "KREAM 검색 타임아웃 (90초). "
                "웨일 브라우저가 열려있고 KREAM 확장앱이 활성화되어 있는지 확인해주세요."
            )

    async def get_product(self, product_id: str) -> dict[str, Any]:
        """KREAM 상품 상세 조회 — SSR HTML 파싱 (확장앱 불필요).

        KREAM 상품 페이지를 직접 HTTP GET → HTML에서 기본 데이터를 추출한다.
        """
        import re as _re
        import html as _html

        url = f"https://kream.co.kr/products/{product_id}"
        timeout = httpx.Timeout(20.0, connect=10.0)

        logger.info(f"[KREAM] 상품 상세 조회 (HTTP 파싱): {product_id}")

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": self.HEADERS["User-Agent"],
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "ko-KR,ko;q=0.9",
                },
            )
            if resp.status_code != 200:
                raise Exception(f"KREAM 상품 페이지 요청 실패: HTTP {resp.status_code}")

        text = resp.text

        # og:title에서 상품명 추출
        og_title = ""
        m = _re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"', text)
        if m:
            og_title = _html.unescape(m.group(1))

        # og:image에서 이미지 추출
        og_image = ""
        m = _re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]*)"', text)
        if m:
            og_image = m.group(1).split("?")[0]

        # 브랜드 추출 (title에서)
        brand = ""
        name = og_title
        # KREAM 타이틀 형식: "브랜드 상품명 | KREAM"
        if " | " in og_title:
            name = og_title.split(" | ")[0].strip()

        # 가격 추출 (JSON-LD 또는 meta 태그)
        price = 0
        price_match = _re.search(r'"price"\s*:\s*"?(\d+)"?', text)
        if price_match:
            price = int(price_match.group(1))

        # 추가 이미지 추출
        images = [og_image] if og_image else []

        return {
            "name": name,
            "brand": brand,
            "salePrice": price,
            "originalPrice": price,
            "images": images,
            "options": [],
            "category": "",
        }

    async def get_product_via_extension(self, product_id: str) -> dict[str, Any]:
        """KREAM 상품 상세 조회 (확장앱 큐 방식, 최대 90초 대기).

        브라우저 확장앱으로 옵션/사이즈 등 세부 데이터까지 수집.
        """
        request_id = str(uuid.uuid4())

        KreamClient.collect_queue.append(
            {
                "requestId": request_id,
                "productId": product_id,
                "url": f"https://kream.co.kr/products/{product_id}",
            }
        )
        logger.info(f"[KREAM] 수집 요청 큐 등록 (확장앱): {product_id} ({request_id})")

        loop = asyncio.get_event_loop()
        future: asyncio.Future[Any] = loop.create_future()
        KreamClient.collect_resolvers[request_id] = future

        try:
            result = await asyncio.wait_for(future, timeout=90.0)
            return result if isinstance(result, dict) else {}
        except asyncio.TimeoutError:
            KreamClient.collect_resolvers.pop(request_id, None)
            raise Exception(
                "KREAM 상품 조회 타임아웃 (90초). "
                "웨일 브라우저가 열려있고 KREAM 확장앱이 활성화되어 있는지 확인해주세요."
            )

    # ------------------------------------------------------------------
    # Prices
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
                        err_data.get("message") or f"매도 입찰 실패: {resp.status_code}"
                    ),
                }
            bid_data = resp.json()
            logger.info(f"[KREAM] 매도 입찰 등록: {product_id} / {size} / {price:,}원")
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
                "message": "매도 입찰 취소 완료"
                if resp.status_code in (200, 204)
                else "취소 실패",
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
