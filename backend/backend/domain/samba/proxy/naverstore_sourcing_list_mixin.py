"""네이버스토어 상품 목록/검색 믹스인.

`NaverStoreSourcingClient` 의 목록 관련 메서드를 격리한 mixin.
메인 클래스에 `_build_proxies / _extract_store_name / _extract_category_id /
resolve_channel_uid / BASE_URL / HEADERS / _proxy_url / _timeout` 등이 이미
존재함을 가정한다(실제 상속 시 문제 없음).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional

from backend.domain.samba.proxy.naverstore_sourcing_collect_script import (
    SUBPROCESS_COLLECT_SCRIPT as _SUBPROCESS_COLLECT_SCRIPT,
)
from backend.utils.logger import logger


class NaverStoreListMixin:
    """스토어 상품 목록/검색 인터페이스.

    `NaverStoreSourcingClient` 와 함께 사용하도록 설계됨.
    런타임 dependency: self.BASE_URL / HEADERS / _build_proxies() /
    _timeout / _extract_store_name / _extract_category_id / resolve_channel_uid /
    _proxy_url / _last_channel_uid / _last_store_name.
    """

    # ------------------------------------------------------------------
    # 스토어 상품 목록
    # ------------------------------------------------------------------

    async def get_store_products(
        self,
        store_url: str,
        page: int = 1,
        page_size: int = 40,
        sort_type: str = "POPULAR",
    ) -> dict[str, Any]:
        """스토어 전체 상품 목록 조회.

        Args:
            store_url: 스마트스토어 URL
            page: 페이지 번호 (1부터)
            page_size: 페이지당 상품 수 (기본 40)
            sort_type: 정렬 (POPULAR, RECENT, LOW_PRICE, HIGH_PRICE, REVIEW)

        Returns:
            {
                "products": [...],
                "totalCount": int,
                "page": int,
                "pageSize": int,
                "channelUid": str,
                "storeName": str,
            }
        """
        channel_uid = await self.resolve_channel_uid(store_url)  # type: ignore[attr-defined]
        if not channel_uid:
            return {
                "products": [],
                "totalCount": 0,
                "error": "channelUid 추출 실패",
            }

        store_name = self._extract_store_name(store_url) or ""  # type: ignore[attr-defined]
        api_url = (
            f"{self.BASE_URL}/i/v2/channels/{channel_uid}"  # type: ignore[attr-defined]
            f"/categories/ALL/products"
            f"?categorySearchType=STDCATG"
            f"&sortType={sort_type}"
            f"&page={page}"
            f"&pageSize={page_size}"
            f"&deduplicateGroupEpId=true"
        )

        logger.info(
            f"[NAVERSTORE] 상품 목록 조회: {store_name} (page={page}, size={page_size})"
        )

        try:
            from curl_cffi.requests import AsyncSession

            async with AsyncSession(
                timeout=self._timeout,  # type: ignore[attr-defined]
                proxies=self._build_proxies(),  # type: ignore[attr-defined]
                impersonate="chrome",
            ) as session:
                resp = await session.get(
                    api_url,
                    headers={
                        **self.HEADERS,  # type: ignore[attr-defined]
                        "Referer": f"{self.BASE_URL}/{store_name}",  # type: ignore[attr-defined]
                    },
                )
                if resp.status_code != 200:
                    logger.error(
                        f"[NAVERSTORE] 상품 목록 HTTP {resp.status_code}: {store_name}"
                    )
                    return {
                        "products": [],
                        "totalCount": 0,
                        "error": f"HTTP {resp.status_code}",
                    }

                data = resp.json()

            raw_products = data.get("simpleProducts", [])
            total_count = data.get("totalCount", 0)
            now_iso = datetime.now(tz=timezone.utc).isoformat()

            products = []
            for raw in raw_products:
                product = self._transform_list_product(
                    raw, channel_uid, store_name, now_iso
                )
                if product:
                    products.append(product)

            logger.info(
                f"[NAVERSTORE] 상품 목록 완료: {store_name} — "
                f"{len(products)}개 (전체 {total_count}개)"
            )

            return {
                "products": products,
                "totalCount": total_count,
                "page": page,
                "pageSize": page_size,
                "channelUid": channel_uid,
                "storeName": store_name,
            }

        except Exception as e:
            logger.error(f"[NAVERSTORE] 상품 목록 실패: {store_name} — {e}")
            return {"products": [], "totalCount": 0, "error": str(e)}

    def _transform_list_product(
        self,
        raw: dict[str, Any],
        channel_uid: str,
        store_name: str,
        now_iso: str,
    ) -> Optional[dict[str, Any]]:
        """목록 API 응답을 표준 상품 dict로 변환."""
        product_id = raw.get("id")
        name = raw.get("name") or raw.get("dispName", "")
        if not product_id or not name:
            return None

        sale_price = raw.get("salePrice", 0)
        benefits = raw.get("benefitsView", {})
        discounted_price = benefits.get("discountedSalePrice", 0) or sale_price
        discount_rate = benefits.get("discountedRatio", 0)

        # 카테고리
        category_info = raw.get("category", {})
        category_str = ""
        if isinstance(category_info, dict):
            category_str = category_info.get("wholeCategoryName", "")
            if not category_str:
                category_str = category_info.get("categoryName", "")

        # 브랜드/제조사
        search_info = raw.get("naverShoppingSearchInfo", {})
        brand = search_info.get("brandName", "")
        manufacturer = search_info.get("manufacturerName", "")

        # 이미지
        thumbnail = raw.get("representativeImageUrl", "")

        # 리뷰
        review_info = raw.get("reviewAmount", {})
        review_count = review_info.get("totalReviewCount", 0)
        review_score = review_info.get("averageReviewScore", 0)

        # 배송
        delivery_info = raw.get("productDeliveryInfo", {})
        delivery_fee_type = delivery_info.get("deliveryFeeType", "")

        return {
            "siteProductId": str(product_id),
            "name": name,
            "brand": brand,
            "manufacturer": manufacturer,
            "originalPrice": sale_price,
            "salePrice": discounted_price,
            "discountRate": discount_rate,
            "thumbnailImageUrl": thumbnail,
            "category": category_str,
            "categoryId": category_info.get("categoryId", ""),
            "reviewCount": review_count,
            "reviewScore": review_score,
            "freeDelivery": delivery_fee_type == "FREE",
            "optionUsable": raw.get("optionUsable", False),
            "storeName": store_name,
            "channelUid": channel_uid,
            "sourceSite": "NAVERSTORE",
            "sourceUrl": (f"{self.BASE_URL}/{store_name}/products/{product_id}"),  # type: ignore[attr-defined]
            "collectedAt": now_iso,
        }

    async def get_store_products_multi(
        self,
        store_url: str,
        total_count: int = 100,
        page_size: int = 40,
        sort_type: str = "POPULAR",
        page_delay: float = 2.0,
        cookies: Optional[str] = None,
    ) -> dict[str, Any]:
        """멀티페이지 상품 목록 조회 — 하나의 세션에서 여러 페이지를 순회.

        2페이지부터는 쿠키 필요 (네이버 인증 요구).

        Returns:
            {
                "products": [...],
                "totalCount": int (스토어 전체),
                "fetchedCount": int (실제 수집),
                "channelUid": str,
                "storeName": str,
            }
        """
        import math

        channel_uid = await self.resolve_channel_uid(store_url)  # type: ignore[attr-defined]
        if not channel_uid:
            return {"products": [], "totalCount": 0, "error": "channelUid 추출 실패"}

        store_name = self._extract_store_name(store_url) or ""  # type: ignore[attr-defined]
        category_id = self._extract_category_id(store_url) or "ALL"  # type: ignore[attr-defined]
        pages_needed = math.ceil(total_count / page_size)
        all_products: list[dict] = []
        total_in_store = 0
        now_iso = datetime.now(tz=timezone.utc).isoformat()

        logger.info(
            f"[NAVERSTORE] 수집 시작: {store_name} (카테고리={'전체' if category_id == 'ALL' else category_id}, 목표={total_count}개)"
        )

        try:
            from curl_cffi.requests import AsyncSession

            # 쿠키가 있으면 프록시 불필요
            proxies = None if cookies else self._build_proxies()  # type: ignore[attr-defined]
            async with AsyncSession(
                timeout=self._timeout,  # type: ignore[attr-defined]
                proxies=proxies,
                impersonate="chrome",
            ) as session:
                for page_num in range(1, pages_needed + 1):
                    if page_num > 1:
                        await asyncio.sleep(page_delay)

                    # 원본 로직(efa38e9b)과 동일: STDCATG 사용
                    api_url = (
                        f"{self.BASE_URL}/i/v2/channels/{channel_uid}"  # type: ignore[attr-defined]
                        f"/categories/{category_id}/products"
                        f"?categorySearchType=STDCATG"
                        f"&sortType={sort_type}"
                        f"&page={page_num}"
                        f"&pageSize={page_size}"
                        f"&deduplicateGroupEpId=true"
                    )

                    req_headers = {
                        **self.HEADERS,  # type: ignore[attr-defined]
                        "Referer": f"{self.BASE_URL}/{store_name}/category/{category_id}",  # type: ignore[attr-defined]
                    }
                    if cookies:
                        req_headers["Cookie"] = cookies

                    logger.info(
                        f"[NAVERSTORE] 상품 목록 조회: {store_name} (page={page_num}, size={page_size}, cookies={'Y' if cookies else 'N'})"
                    )

                    resp = await session.get(api_url, headers=req_headers)

                    if resp.status_code != 200:
                        logger.error(
                            f"[NAVERSTORE] 상품 목록 HTTP {resp.status_code}: {store_name} page={page_num}"
                        )
                        break

                    data = resp.json()
                    raw_products = data.get("simpleProducts", [])

                    logger.info(
                        f"[NAVERSTORE] page={page_num} totalCount={data.get('totalCount')}, "
                        f"simpleProducts={len(raw_products)}"
                    )

                    if page_num == 1:
                        total_in_store = data.get("totalCount", 0)

                    if not raw_products:
                        logger.info(
                            f"[NAVERSTORE] 상품 목록 빈 페이지: page={page_num}"
                        )
                        break

                    for raw in raw_products:
                        product = self._transform_list_product(
                            raw, channel_uid, store_name, now_iso
                        )
                        if product:
                            all_products.append(product)

                    logger.info(
                        f"[NAVERSTORE] 상품 목록 완료: {store_name} — "
                        f"page={page_num}, {len(raw_products)}개 (누적 {len(all_products)}개)"
                    )

                    if len(all_products) >= total_count:
                        all_products = all_products[:total_count]
                        break

                    if len(raw_products) < page_size:
                        break

        except Exception as e:
            logger.error(f"[NAVERSTORE] 멀티페이지 목록 실패: {store_name} — {e}")

        return {
            "products": all_products,
            "totalCount": total_in_store,
            "fetchedCount": len(all_products),
            "channelUid": channel_uid,
            "storeName": store_name,
        }

    # ------------------------------------------------------------------
    # search() — worker 호환 인터페이스
    # ------------------------------------------------------------------

    async def search(
        self,
        keyword: str,
        max_count: int = 100,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """잡워커 _collect_direct_api 호환 인터페이스.

        keyword = 스마트스토어 URL (전체 또는 카테고리).
        curl_cffi가 SQLAlchemy greenlet과 충돌하므로
        별도 subprocess에서 curl_cffi를 실행하여 완전 격리한다.
        """
        import sys

        store_url = keyword
        store_name = self._extract_store_name(store_url) or ""  # type: ignore[attr-defined]
        category_id = self._extract_category_id(store_url) or "ALL"  # type: ignore[attr-defined]
        proxy_url = self._proxy_url or ""  # type: ignore[attr-defined]

        # 별도 프로세스에서 curl_cffi 실행 — greenlet 충돌 원천 차단
        script = _SUBPROCESS_COLLECT_SCRIPT

        logger.info(
            f"[NAVERSTORE-WORKER] subprocess 수집 시작: {store_name} "
            f"(카테고리={'전체' if category_id == 'ALL' else category_id}, "
            f"목표={max_count}개, 프록시={'Y' if proxy_url else 'N'})"
        )

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            script,
            store_url,
            str(max_count),
            proxy_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        # subprocess stderr 진단 로그 항상 출력
        if stderr:
            for line in stderr.decode(errors="replace").strip().splitlines():
                logger.info(f"[NAVERSTORE-SUB] {line}")

        if proc.returncode != 0:
            logger.error(
                f"[NAVERSTORE-WORKER] subprocess 비정상 종료: code={proc.returncode}"
            )
            return {"products": [], "total": 0}

        try:
            result = json.loads(stdout.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(
                f"[NAVERSTORE-WORKER] JSON 파싱 실패: {e}, "
                f"stdout={stdout.decode(errors='replace')[:200]}"
            )
            return {"products": [], "total": 0}

        products = result.get("products", [])
        total = result.get("total", 0)
        # 상세조회용 채널/스토어 정보 캐시 (worker 가 get_detail 호출 시 재사용)
        _cuid = result.get("channelUid") or ""
        _sname = result.get("storeName") or store_name
        if _cuid:
            self._last_channel_uid = _cuid  # type: ignore[attr-defined]
        if _sname:
            self._last_store_name = _sname  # type: ignore[attr-defined]
        logger.info(
            f"[NAVERSTORE-WORKER] subprocess 수집 완료: {store_name} — "
            f"{len(products)}개 (스토어 전체 {total}개, channelUid={_cuid[:10]}...)"
        )
        return {"products": products, "total": total}
