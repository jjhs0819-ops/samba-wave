"""통합 소싱 큐 — 확장앱 기반 상품 수집 큐 관리.

KREAM 패턴과 동일: 백엔드가 큐에 작업 추가 → 확장앱이 폴링 → 탭 열어 DOM 파싱 → 결과 전송.
ABCmart, GrandStage, OKmall, 롯데ON, GSShop 5개 사이트 지원.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from backend.utils.logger import logger

# 사이트별 검색 URL 템플릿
SITE_SEARCH_URLS: dict[str, str] = {
    "ABCmart": "https://www.a-rt.com/display/search-word/result?searchWord={keyword}",
    "GrandStage": "https://www.a-rt.com/display/search-word/result?searchWord={keyword}&channel=10002",
    "OKmall": "https://www.okmall.com/products/list?keyword={keyword}",
    "LOTTEON": "https://www.lotteon.com/search/search/search.ecn?render=search&platform=pc&q={keyword}",
    "GSShop": "https://www.gsshop.com/search/searchMain.gs?tq={keyword}",
    "ElandMall": "https://www.elandmall.com/search/search.action?kwd={keyword}",
    "SSF": "https://www.ssfshop.com/search?keyword={keyword}",
}

# 사이트별 상품 상세 URL 템플릿
SITE_DETAIL_URLS: dict[str, str] = {
    "ABCmart": "https://www.a-rt.com/product?prdtNo={product_id}",
    "GrandStage": "https://www.a-rt.com/product?prdtNo={product_id}&tChnnlNo=10002",
    "OKmall": "https://www.okmall.com/products/detail/{product_id}",
    "LOTTEON": "https://www.lotteon.com/product/productDetail.lotte?spdNo={product_id}",
    "GSShop": "https://www.gsshop.com/prd/prd.gs?prdid={product_id}",
    "ElandMall": "https://www.elandmall.com/goods/goods.action?goodsNo={product_id}",
    "SSF": "https://www.ssfshop.com/goods/{product_id}",
    "FashionPlus": "https://www.fashionplus.co.kr/goods/detail/{product_id}",
}


class SourcingQueue:
    """통합 소싱 수집 큐 (싱글턴, 클래스 변수)."""

    # 수집 큐: [{requestId, site, type, url, keyword?, productId?}]
    queue: list[dict[str, Any]] = []
    # 결과 대기: {requestId: asyncio.Future}
    resolvers: dict[str, asyncio.Future[Any]] = {}

    @classmethod
    def add_search_job(cls, site: str, keyword: str) -> tuple[str, asyncio.Future[Any]]:
        """검색 작업 큐에 추가. (requestId, future) 반환."""
        request_id = str(uuid.uuid4())[:8]
        url_template = SITE_SEARCH_URLS.get(site, "")
        if not url_template:
            raise ValueError(f"지원하지 않는 소싱처: {site}")

        url = url_template.replace("{keyword}", keyword)
        loop = asyncio.get_event_loop()
        future: asyncio.Future[Any] = loop.create_future()

        cls.queue.append(
            {
                "requestId": request_id,
                "site": site,
                "type": "search",
                "url": url,
                "keyword": keyword,
            }
        )
        cls.resolvers[request_id] = future
        logger.info(f"[소싱큐] 검색 추가: {site} '{keyword}' (id={request_id})")
        return request_id, future

    @classmethod
    def add_detail_job(
        cls, site: str, product_id: str
    ) -> tuple[str, asyncio.Future[Any]]:
        """상세조회 작업 큐에 추가. (requestId, future) 반환."""
        request_id = str(uuid.uuid4())[:8]
        url_template = SITE_DETAIL_URLS.get(site, "")
        if not url_template:
            raise ValueError(f"지원하지 않는 소싱처: {site}")

        url = url_template.replace("{product_id}", product_id)
        loop = asyncio.get_event_loop()
        future: asyncio.Future[Any] = loop.create_future()

        cls.queue.append(
            {
                "requestId": request_id,
                "site": site,
                "type": "detail",
                "url": url,
                "productId": product_id,
            }
        )
        cls.resolvers[request_id] = future
        logger.info(f"[소싱큐] 상세 추가: {site} #{product_id} (id={request_id})")
        return request_id, future

    @classmethod
    def get_next_job(cls) -> dict[str, Any]:
        """큐에서 다음 작업 가져오기 (확장앱 폴링용)."""
        if cls.queue:
            job = cls.queue.pop(0)
            return {"hasJob": True, **job}
        return {"hasJob": False}

    @classmethod
    def resolve_job(cls, request_id: str, data: dict[str, Any]) -> bool:
        """작업 결과 전달 (확장앱 → 백엔드)."""
        future = cls.resolvers.pop(request_id, None)
        if future and not future.done():
            future.set_result(data)
            logger.info(
                f"[소싱큐] 결과 수신: id={request_id}, success={data.get('success')}"
            )
            return True
        return False
