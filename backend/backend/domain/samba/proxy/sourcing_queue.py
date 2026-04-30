"""통합 소싱 큐 — 확장앱 기반 상품 수집 큐 관리.

KREAM 패턴과 동일: 백엔드가 큐에 작업 추가 → 확장앱이 폴링 → 탭 열어 DOM 파싱 → 결과 전송.
ABCmart, GrandStage, REXMONDE, 롯데ON, GSShop 5개 사이트 지원.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from backend.shutdown_state import is_shutting_down
from backend.utils.logger import logger

# 오토튠 등 백엔드 자동화 경로에서 add_detail_job을 호출할 때
# 기본 소유자(작업을 처리해야 할 브라우저의 deviceId)를 설정하는 전역 저장소.
# autotune_start에서 set_autotune_owner로 세팅하고, autotune_stop에서 리셋한다.
# 이 deviceId와 일치하는 확장앱만 해당 작업을 집어가게 된다.
_autotune_owner_device_id: str = ""

# 사이트별 owner override (PC 분산용).
# 예: {"ABCmart": "device_A", "LOTTEON": "device_B"} — ABCmart 작업은 PC A,
# LOTTEON 작업은 PC B로 발행. 매핑 없는 사이트는 _autotune_owner_device_id로 fallback.
# autotune_stop / clear_autotune_owners()에서 비워준다.
_autotune_owner_by_site: dict[str, str] = {}


def set_autotune_owner(device_id: str) -> None:
    """오토튠이 발행하는 작업의 기본 소유자 deviceId 설정.

    사이트별 override(set_autotune_owner_for_site)가 없는 사이트의 fallback으로 사용된다.
    """
    global _autotune_owner_device_id
    _autotune_owner_device_id = (device_id or "").strip()


def set_autotune_owner_for_site(site: str, device_id: str) -> None:
    """사이트별 owner 매핑 — PC 분산용.

    예) set_autotune_owner_for_site("ABCmart", "device_A")
        set_autotune_owner_for_site("LOTTEON", "device_B")

    빈 device_id 전달 시 해당 사이트 매핑 제거(기본 owner로 fallback).
    """
    global _autotune_owner_by_site
    site_key = (site or "").strip()
    dev = (device_id or "").strip()
    if not site_key:
        return
    if dev:
        _autotune_owner_by_site[site_key] = dev
        logger.info(f"[소싱큐] 사이트별 owner 매핑: {site_key} → {dev[:8]}")
    else:
        if site_key in _autotune_owner_by_site:
            _autotune_owner_by_site.pop(site_key, None)
            logger.info(f"[소싱큐] 사이트별 owner 매핑 제거: {site_key}")


def clear_autotune_owners() -> None:
    """오토튠 종료 시 모든 owner(기본 + 사이트별) 리셋."""
    global _autotune_owner_device_id, _autotune_owner_by_site
    _autotune_owner_device_id = ""
    _autotune_owner_by_site = {}
    logger.info("[소싱큐] 오토튠 owner 전체 리셋")


def get_autotune_owner(site: str | None = None) -> str:
    """사이트별 owner 조회. 사이트 매핑이 있으면 그걸, 없으면 기본 owner를 반환한다."""
    if site:
        site_key = site.strip()
        if site_key in _autotune_owner_by_site:
            return _autotune_owner_by_site[site_key]
    return _autotune_owner_device_id


def get_autotune_owner_mapping() -> dict[str, str]:
    """현재 사이트별 owner 매핑 + 기본 owner 조회 (디버그/모니터링용)."""
    return {
        "default": _autotune_owner_device_id,
        "by_site": dict(_autotune_owner_by_site),
    }


# 사이트별 검색 URL 템플릿
SITE_SEARCH_URLS: dict[str, str] = {
    "ABCmart": "https://www.a-rt.com/display/search-word/result?searchWord={keyword}",
    "GrandStage": "https://www.a-rt.com/display/search-word/result?searchWord={keyword}&channel=10002",
    "REXMONDE": "https://www.okmall.com/products/list?keyword={keyword}",
    "LOTTEON": "https://www.lotteon.com/csearch/search/search?render=search&platform=pc&mallId=2&q={keyword}",
    "GSShop": "https://www.gsshop.com/shop/search/main.gs?tq={keyword}",
    "SSG": "https://department.ssg.com/search?query={keyword}",
    "ElandMall": "https://www.elandmall.com/search/search.action?kwd={keyword}",
    "SSF": "https://www.ssfshop.com/search?keyword={keyword}",
}

# 사이트별 상품 상세 URL 템플릿
SITE_DETAIL_URLS: dict[str, str] = {
    # 서브도메인별로 cookie 격리 — www.a-rt.com에서 열면 abcmart/grandstage cookie
    # 자동 포함 안 됨 → 비로그인 페이지 → "최대 혜택가" 미표시 → DOM 파싱 fallback으로
    # sale_price를 best_benefit_price로 보내 cost가 멤버십 할인 미반영된 값으로 박힘.
    "ABCmart": "https://abcmart.a-rt.com/product?prdtNo={product_id}",
    "GrandStage": "https://grandstage.a-rt.com/product?prdtNo={product_id}&tChnnlNo=10002",
    "REXMONDE": "https://www.okmall.com/products/detail/{product_id}",
    "LOTTEON": "https://www.lotteon.com/p/product/{product_id}",
    "GSShop": "https://www.gsshop.com/prd/prd.gs?prdid={product_id}",
    "SSG": "https://department.ssg.com/item/itemView.ssg?itemId={product_id}&siteNo=6009",
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
    def _ensure_accepting_jobs(cls) -> None:
        if is_shutting_down():
            raise RuntimeError("server is shutting down")

    @classmethod
    def add_search_job(
        cls,
        site: str,
        keyword: str,
        url: str | None = None,
        max_count: int | None = None,
        *,
        owner_device_id: str | None = None,
    ) -> tuple[str, asyncio.Future[Any]]:
        """검색 작업 큐에 추가. (requestId, future) 반환.

        url: 호출자가 원본 검색 URL(파라미터 포함)을 직접 넘길 수 있음.
             없으면 SITE_SEARCH_URLS 템플릿에 keyword만 치환해서 사용.
        max_count: 확장앱에 최대 수집 건수 힌트 전달.
        owner_device_id: 작업을 집어가야 할 확장앱 deviceId. None이면 오토튠 전역값을 사용.
        """
        cls._ensure_accepting_jobs()
        request_id = str(uuid.uuid4())[:8]
        if not url:
            url_template = SITE_SEARCH_URLS.get(site, "")
            if not url_template:
                raise ValueError(f"지원하지 않는 소싱처: {site}")
            url = url_template.replace("{keyword}", keyword)

        loop = asyncio.get_event_loop()
        future: asyncio.Future[Any] = loop.create_future()

        if owner_device_id is None:
            # 사이트별 매핑 우선 → 없으면 기본 owner (PC 분산 지원)
            owner_device_id = get_autotune_owner(site)

        job: dict[str, Any] = {
            "requestId": request_id,
            "site": site,
            "type": "search",
            "url": url,
            "keyword": keyword,
            "ownerDeviceId": owner_device_id or "",
        }
        if max_count is not None:
            job["maxCount"] = max_count
        cls.queue.append(job)
        cls.resolvers[request_id] = future
        _owner_tag = f" owner={owner_device_id[:8]}" if owner_device_id else ""
        logger.info(
            f"[소싱큐] 검색 추가: {site} '{keyword}' (id={request_id}){_owner_tag}"
        )
        return request_id, future

    @classmethod
    def add_detail_job(
        cls,
        site: str,
        product_id: str,
        *,
        sitm_no: str = "",
        url: str = "",
        extra: dict[str, Any] | None = None,
        owner_device_id: str | None = None,
    ) -> tuple[str, asyncio.Future[Any]]:
        """상세조회 작업 큐에 추가. (requestId, future) 반환.

        sitm_no: LOTTEON sitmNo — 전달 시 확장앱이 탭 없이 pbf API 직접 호출.
        url: 비어있지 않으면 SITE_DETAIL_URLS 템플릿 대신 직접 사용 (NAVERSTORE 등 템플릿만으로 부족한 경우).
        extra: job dict에 병합할 추가 필드 (channelUid, storeName 등).
        owner_device_id: 작업을 집어가야 할 확장앱 deviceId. None이면 오토튠 전역값을 사용.
        """
        cls._ensure_accepting_jobs()
        request_id = str(uuid.uuid4())[:8]
        if not url:
            url_template = SITE_DETAIL_URLS.get(site, "")
            if not url_template:
                raise ValueError(f"지원하지 않는 소싱처: {site}")
            url = url_template.replace("{product_id}", product_id)
        loop = asyncio.get_event_loop()
        future: asyncio.Future[Any] = loop.create_future()

        if owner_device_id is None:
            # 사이트별 매핑 우선 → 없으면 기본 owner (PC 분산 지원)
            owner_device_id = get_autotune_owner(site)

        job: dict[str, Any] = {
            "requestId": request_id,
            "site": site,
            "type": "detail",
            "url": url,
            "productId": product_id,
            "ownerDeviceId": owner_device_id or "",
        }
        if sitm_no:
            job["sitmNo"] = sitm_no
        if extra:
            job.update(extra)
        cls.queue.append(job)
        cls.resolvers[request_id] = future
        _owner_tag = f" owner={owner_device_id[:8]}" if owner_device_id else ""
        logger.info(
            f"[소싱큐] 상세 추가: {site} #{product_id} (id={request_id}){_owner_tag}"
        )
        return request_id, future

    @classmethod
    def get_next_job(cls, device_id: str | None = None) -> dict[str, Any]:
        """큐에서 다음 작업 가져오기 (확장앱 폴링용).

        device_id가 주어지면 해당 deviceId가 소유자인 작업만 반환한다.
        소유자가 지정되지 않은(legacy) 작업은 deviceId가 있든 없든 누구나 집어갈 수 있다.
        device_id가 비어 있으면(구버전 확장앱) 소유자 없는 작업만 반환 — 오토튠이 특정 PC로
        라우팅한 작업이 엉뚱한 PC에서 열리는 현상을 방지한다.
        """
        if is_shutting_down():
            return {"hasJob": False, "shuttingDown": True}
        if not cls.queue:
            return {"hasJob": False}

        device_id = (device_id or "").strip()
        for idx, job in enumerate(cls.queue):
            owner = (job.get("ownerDeviceId") or "").strip()
            if not owner:
                # 소유자 미지정 작업 — 어느 확장앱이든 처리 가능 (기존 동작)
                cls.queue.pop(idx)
                return {"hasJob": True, **job}
            if device_id and owner == device_id:
                cls.queue.pop(idx)
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
            _prods = data.get("products") or []
            _err = data.get("error") or ""
            logger.info(
                f"[소싱큐] 결과 수신: id={request_id}, success={data.get('success')}, "
                f"products={len(_prods)}, error={_err[:100]}"
            )
            return True
        return False

    @classmethod
    def cancel_all(cls, reason: str = "server is shutting down") -> None:
        """Release pending waiters during process shutdown."""
        cls.queue.clear()
        futures = list(cls.resolvers.items())
        cls.resolvers.clear()
        for request_id, future in futures:
            if future.done():
                continue
            exc = RuntimeError(reason)
            try:
                loop = future.get_loop()
                loop.call_soon_threadsafe(future.set_exception, exc)
            except RuntimeError:
                if not future.done():
                    future.set_exception(exc)
            logger.info(f"[sourcing queue] shutdown cancel: {request_id}")
