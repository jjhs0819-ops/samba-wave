"""통합 소싱 큐 — 확장앱 기반 상품 수집 큐 관리.

KREAM 패턴과 동일: 백엔드가 큐에 작업 추가 → 확장앱이 폴링 → 탭 열어 DOM 파싱 → 결과 전송.
ABCmart, GrandStage, REXMONDE, 롯데ON, GSShop 5개 사이트 지원.
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
    "REXMONDE": "https://www.okmall.com/products/list?keyword={keyword}",
    "LOTTEON": "https://www.lotteon.com/csearch/search/search?render=search&platform=pc&mallId=2&q={keyword}",
    "GSShop": "https://www.gsshop.com/shop/search/main.gs?tq={keyword}",
    "ElandMall": "https://www.elandmall.com/search/search.action?kwd={keyword}",
    "SSF": "https://www.ssfshop.com/search?keyword={keyword}",
}

# 사이트별 상품 상세 URL 템플릿
SITE_DETAIL_URLS: dict[str, str] = {
    "ABCmart": "https://www.a-rt.com/product?prdtNo={product_id}",
    "GrandStage": "https://www.a-rt.com/product?prdtNo={product_id}&tChnnlNo=10002",
    "REXMONDE": "https://www.okmall.com/products/detail/{product_id}",
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
    def add_search_job(
        cls,
        site: str,
        keyword: str,
        url: str | None = None,
        max_count: int | None = None,
    ) -> tuple[str, asyncio.Future[Any]]:
        """검색 작업 큐에 추가. (requestId, future) 반환.

        url: 호출자가 원본 검색 URL(파라미터 포함)을 직접 넘길 수 있음.
             없으면 SITE_SEARCH_URLS 템플릿에 keyword만 치환해서 사용.
        max_count: 확장앱에 최대 수집 건수 힌트 전달.
        """
        request_id = str(uuid.uuid4())[:8]
        if not url:
            url_template = SITE_SEARCH_URLS.get(site, "")
            if not url_template:
                raise ValueError(f"지원하지 않는 소싱처: {site}")
            url = url_template.replace("{keyword}", keyword)

        loop = asyncio.get_event_loop()
        future: asyncio.Future[Any] = loop.create_future()

        job: dict[str, Any] = {
            "requestId": request_id,
            "site": site,
            "type": "search",
            "url": url,
            "keyword": keyword,
        }
        if max_count is not None:
            job["maxCount"] = max_count
        cls.queue.append(job)
        cls.resolvers[request_id] = future
        logger.info(f"[소싱큐] 검색 추가: {site} '{keyword}' (id={request_id})")
        return request_id, future

    @classmethod
    def add_detail_job(
        cls, site: str, product_id: str, *, sitm_no: str = ""
    ) -> tuple[str, asyncio.Future[Any]]:
        """상세조회 작업 큐에 추가. (requestId, future) 반환.

        sitm_no: LOTTEON sitmNo — 전달 시 확장앱이 탭 없이 pbf API 직접 호출.
        """
        request_id = str(uuid.uuid4())[:8]
        url_template = SITE_DETAIL_URLS.get(site, "")
        if not url_template:
            raise ValueError(f"지원하지 않는 소싱처: {site}")

        url = url_template.replace("{product_id}", product_id)
        loop = asyncio.get_event_loop()
        future: asyncio.Future[Any] = loop.create_future()

        job: dict[str, Any] = {
            "requestId": request_id,
            "site": site,
            "type": "detail",
            "url": url,
            "productId": product_id,
        }
        if sitm_no:
            job["sitmNo"] = sitm_no
        cls.queue.append(job)
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
        """작업 결과 전달 (확장앱 → 백엔드).

        Future가 워커 스레드의 이벤트 루프에서 생성되었을 수 있으므로
        call_soon_threadsafe로 안전하게 resolve한다.
        """
        future = cls.resolvers.pop(request_id, None)
        if future and not future.done():
            try:
                loop = future.get_loop()
                loop.call_soon_threadsafe(future.set_result, data)
            except RuntimeError:
                # 루프가 닫혔으면 직접 set (같은 스레드일 수도 있음)
                if not future.done():
                    future.set_result(data)
            logger.info(
                f"[소싱큐] 결과 수신: id={request_id}, success={data.get('success')}"
            )
            return True
        return False
