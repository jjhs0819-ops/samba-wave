"""네이버스토어 소싱용 클라이언트 — 내부 JSON API 기반.

스마트스토어 내부 API를 직접 호출하여 상품 목록/상세를 수집한다.
curl_cffi를 사용하여 TLS fingerprint를 브라우저처럼 위장한다.
worker 컨텍스트에서는 동기 Session + asyncio.to_thread로 greenlet 충돌 회피.

핵심 API:
  - 상품 목록: GET /i/v2/channels/{channelUid}/categories/ALL/products?page=1&pageSize=40
  - 상품 상세: GET /i/v2/channels/{channelUid}/products/{productId}?withWindow=false
"""

from __future__ import annotations

import json
import re
from typing import Optional

from backend.domain.samba.proxy.naverstore_sourcing_detail_mixin import (
    NaverStoreDetailMixin,
)
from backend.domain.samba.proxy.naverstore_sourcing_list_mixin import (
    NaverStoreListMixin,
)
from backend.utils.logger import logger


def _get_proxy_url() -> str:
    """수집용 프록시 URL 가져오기 — DB 설정 페이지(/samba/settings) 기반."""
    try:
        from backend.domain.samba.collector.refresher import get_collect_proxy_url

        return (get_collect_proxy_url() or "").strip()
    except Exception:
        return ""


class NaverStoreSourcingClient(NaverStoreListMixin, NaverStoreDetailMixin):
    """네이버스토어 소싱용 클라이언트.

    내부 JSON API를 활용한 상품 목록/상세 조회를 제공한다.
    curl_cffi로 브라우저 TLS fingerprint를 위장하여 봇 차단을 우회한다.

    - 목록/검색 메서드: `NaverStoreListMixin` (naverstore_sourcing_list_mixin.py)
    - 상세 메서드: `NaverStoreDetailMixin` (naverstore_sourcing_detail_mixin.py)
    """

    BASE_URL = "https://smartstore.naver.com"

    HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/136.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://smartstore.naver.com/",
    }

    HTML_HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/136.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }

    # 계정 쿠키 캐시 (프로세스 생애주기 내 60초)
    _cookies_cache: tuple[str, float] = ("", 0.0)

    @classmethod
    async def _fetch_cookies_from_db(cls) -> str:
        """sourcing_account 테이블에서 NAVERSTORE 활성 계정 쿠키 조회.

        additional_fields JSON 의 'cookies' 키 값 반환. 60초 캐싱.
        """
        import time as _time

        cached_val, cached_at = cls._cookies_cache
        if cached_val and (_time.time() - cached_at) < 60:
            return cached_val

        from backend.db.orm import get_read_session
        from backend.domain.samba.sourcing_account.model import SambaSourcingAccount
        from sqlmodel import select

        async with get_read_session() as session:
            stmt = (
                select(SambaSourcingAccount)
                .where(SambaSourcingAccount.site_name == "NAVERSTORE")
                .where(SambaSourcingAccount.is_active == True)  # noqa: E712
                .order_by(SambaSourcingAccount.updated_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            account = result.scalar_one_or_none()

        cookies = ""
        if account and account.additional_fields:
            af = account.additional_fields
            if isinstance(af, dict):
                cookies = str(af.get("cookies") or "").strip()

        cls._cookies_cache = (cookies, _time.time())
        return cookies

    # 상세 API 요청 간 딜레이 (초) — 429 방지
    DETAIL_DELAY: float = 2.0

    def __init__(self, proxy_url: str | None = None) -> None:
        self._proxy_url = proxy_url or _get_proxy_url()
        self._timeout = 20
        # channelUid 캐시: store_name -> channelUid
        self._uid_cache: dict[str, str] = {}

    def _build_proxies(self) -> dict[str, str] | None:
        """프록시 설정 dict 반환."""
        if self._proxy_url:
            return {"https": self._proxy_url, "http": self._proxy_url}
        return None

    # ------------------------------------------------------------------
    # channelUid 추출
    # ------------------------------------------------------------------

    async def resolve_channel_uid(self, store_url: str) -> Optional[str]:
        """스토어 URL에서 channelUid를 추출한다.

        목록 API를 호출하여 응답에서 channelUid를 추출하는 방식을 우선 시도하고,
        실패 시 HTML 파싱으로 폴백한다.
        """
        store_name = self._extract_store_name(store_url)
        if not store_name:
            logger.error(f"[NAVERSTORE] 스토어명 추출 실패: {store_url}")
            return None

        # 캐시 확인
        if store_name in self._uid_cache:
            return self._uid_cache[store_name]

        # HTML 페이지에서 channelUid 추출
        page_url = f"{self.BASE_URL}/{store_name}"
        logger.info(f"[NAVERSTORE] channelUid 조회: {page_url}")

        try:
            from curl_cffi.requests import AsyncSession

            async with AsyncSession(
                timeout=self._timeout,
                proxies=self._build_proxies(),
                impersonate="chrome",
            ) as session:
                resp = await session.get(page_url, headers=self.HTML_HEADERS)
                if resp.status_code != 200:
                    logger.error(
                        f"[NAVERSTORE] 스토어 페이지 HTTP {resp.status_code}: {store_name}"
                    )
                    return None

                html = resp.text
                channel_uid = self._parse_channel_uid(html)
                if channel_uid:
                    self._uid_cache[store_name] = channel_uid
                    logger.info(
                        f"[NAVERSTORE] channelUid 확인: {store_name} -> {channel_uid}"
                    )
                return channel_uid

        except Exception as e:
            logger.error(f"[NAVERSTORE] channelUid 조회 실패: {store_name} — {e}")
            return None

    def _parse_channel_uid(self, html: str) -> Optional[str]:
        """HTML의 __PRELOADED_STATE__에서 channelUid를 추출."""
        # channelUid 패턴: 영숫자 21자리
        m = re.search(r'"channelUid"\s*:\s*"([a-zA-Z0-9]{15,30})"', html)
        if m:
            return m.group(1)

        # __PRELOADED_STATE__ JSON 파싱 시도
        state_match = re.search(r"window\.__PRELOADED_STATE__\s*=\s*", html)
        if state_match:
            start = state_match.end()
            end = html.find(";</script>", start)
            if end > start:
                raw = html[start:end]
                raw = re.sub(r"\bundefined\b", "null", raw)
                try:
                    decoder = json.JSONDecoder()
                    data, _ = decoder.raw_decode(raw)
                    # channel 정보에서 channelUid 추출
                    channel = data.get("channel", {})
                    if isinstance(channel, dict):
                        uid = channel.get("channelUid")
                        if uid:
                            return uid
                    # simpleProductForDetailPage에서 추출
                    spd = data.get("simpleProductForDetailPage", {}).get("A", {})
                    ch = spd.get("channel", {})
                    if isinstance(ch, dict):
                        uid = ch.get("channelUid")
                        if uid:
                            return uid
                except (json.JSONDecodeError, ValueError):
                    pass

        return None

    # ------------------------------------------------------------------
    # URL → 스토어명/카테고리명 파싱 (UI 표시용)
    # ------------------------------------------------------------------

    async def resolve_url_info(self, store_url: str) -> dict[str, str]:
        """URL에서 스토어명 + 카테고리 표시명 추출.

        Returns:
            {"storeName": "coming", "categoryName": "전체상품" | "스니커즈" | ...}

        우선순위: JSON 스코프 매칭 → HTML <title> 파싱 → 메타 API → fallback.
        Why: <title>에는 운영자가 넣은 SEO 키워드(언더스코어 연결)가 들어있어
        실제 메뉴명과 다를 수 있음. JSON 스코프(`"categoryId":"<id>"` 근처의
        `"name":"..."`)는 메뉴 렌더링에 쓰이는 실제 메뉴명이라 더 정확.
        """
        store_name = self._extract_store_name(store_url) or ""
        category_id = self._extract_category_id(store_url)

        # 검색 URL(/search?q=...) → 카테고리명을 "[검색]_{키워드}"로 반환.
        # Why: 검색은 카테고리와 다른 진입 경로라 UI 그룹명에 검색 컨텍스트 명시 필요.
        # /search path 있는데 q= 비어있으면 명시적으로 표시 — silent 전체수집 방지(팀장 리뷰 #56).
        is_search, search_kw = self._parse_search_url(store_url)
        if is_search:
            if search_kw:
                return {"storeName": store_name, "categoryName": f"[검색]_{search_kw}"}
            return {"storeName": store_name, "categoryName": "[검색오류]_키워드없음"}

        # 카테고리 없음 → 전체상품
        if not category_id:
            return {"storeName": store_name, "categoryName": "전체상품"}

        from curl_cffi.requests import AsyncSession

        def _is_seo_keyword_blob(s: str) -> bool:
            """SEO용 언더스코어 키워드 나열인지 판단.

            예: "컨버스_첵테일러_올스타_더블_스텍_하이_로우_리프트_키높이_운동화"
            → 언더스코어 ≥ 3개 + 공백 없음 → 메뉴명이 아니라 SEO 키워드.
            """
            return s.count("_") >= 3 and " " not in s

        # HTML 한 번만 받아서 JSON 스코프 + <title> 둘 다 시도
        html = ""
        try:
            html_url = f"{self.BASE_URL}/{store_name}/category/{category_id}?cp=1"
            async with AsyncSession(
                timeout=self._timeout,
                proxies=self._build_proxies(),
                impersonate="chrome",
            ) as session:
                r = await session.get(html_url, headers=self.HTML_HEADERS)
                if r.status_code == 200:
                    html = r.text
        except Exception as e:
            logger.warning(f"[NAVERSTORE] HTML fetch 실패: {e}")

        # 1) JSON 스코프 매칭 (1순위) — 스토어 메뉴 렌더링용 실제 메뉴명
        #    HTML 내 카테고리 정보는 `"name":"...","categoryId":"<id>",...` 형태.
        #    wholeCategoryName(네이버 표준 카테고리 전체경로)은 제외.
        if html:
            try:
                cid_pattern = rf'"categoryId"\s*:\s*"{re.escape(category_id)}"'
                cat_name = ""
                for m in re.finditer(cid_pattern, html):
                    scope_start = max(0, m.start() - 400)
                    scope_end = min(len(html), m.end() + 400)
                    scope = html[scope_start:scope_end]
                    for field in ("name", "categoryName"):
                        fm = re.search(rf'"{field}"\s*:\s*"([^"]+)"', scope)
                        if fm:
                            raw_name = fm.group(1)
                            try:
                                decoded = json.loads(f'"{raw_name}"')
                            except Exception:
                                decoded = raw_name
                            decoded = decoded.strip()
                            if (
                                decoded
                                and decoded != store_name
                                and not _is_seo_keyword_blob(decoded)
                            ):
                                cat_name = decoded
                                break
                    if cat_name:
                        break
                if cat_name:
                    return {"storeName": store_name, "categoryName": cat_name}
            except Exception as e:
                logger.warning(f"[NAVERSTORE] JSON 스코프 매칭 실패: {e}")

        # 2) HTML <title> 파싱 fallback — JSON 스코프에서 못 찾은 케이스
        #    전형 포맷 예: "스니커즈 : gaia2937 - 네이버 스마트스토어"
        #    단, `_` 3개 이상 연결된 SEO 키워드는 건너뜀.
        if html:
            try:
                m = re.search(r"<title>([^<]+)</title>", html)
                if m:
                    title = m.group(1).strip()
                    for sep in [" : ", " - ", " | "]:
                        if sep in title:
                            candidate = title.split(sep)[0].strip()
                            if (
                                candidate
                                and candidate != store_name
                                and "네이버" not in candidate
                                and "스마트스토어" not in candidate
                                and "브랜드스토어" not in candidate
                                and not _is_seo_keyword_blob(candidate)
                            ):
                                return {
                                    "storeName": store_name,
                                    "categoryName": candidate,
                                }
            except Exception as e:
                logger.warning(f"[NAVERSTORE] <title> 파싱 실패: {e}")

        # 3) 메타 API fallback
        channel_uid = await self.resolve_channel_uid(store_url)
        if channel_uid:
            meta_url = (
                f"{self.BASE_URL}/i/v2/channels/{channel_uid}"
                f"/categories/{category_id}?categoryDisplayType=DISPLAY"
            )
            referer = f"{self.BASE_URL}/{store_name}/category/{category_id}"
            try:
                async with AsyncSession(
                    timeout=self._timeout,
                    proxies=self._build_proxies(),
                    impersonate="chrome",
                ) as session:
                    resp = await session.get(
                        meta_url,
                        headers={**self.HEADERS, "Referer": referer},
                    )
                    if resp.status_code == 200:
                        data = resp.json() or {}
                        cat_name = (
                            data.get("name")
                            or data.get("displayName")
                            or data.get("categoryName")
                            or data.get("title")
                            or ""
                        )
                        if not cat_name:
                            info = (
                                data.get("categoryInfo") or data.get("category") or {}
                            )
                            if isinstance(info, dict):
                                cat_name = (
                                    info.get("name")
                                    or info.get("displayName")
                                    or info.get("categoryName")
                                    or ""
                                )
                        if cat_name and not _is_seo_keyword_blob(cat_name):
                            return {"storeName": store_name, "categoryName": cat_name}
            except Exception as e:
                logger.warning(f"[NAVERSTORE] 메타 API 카테고리명 조회 실패: {e}")

        # 4) 최후 fallback
        return {"storeName": store_name, "categoryName": category_id[:8]}

    # ------------------------------------------------------------------
    # 헬퍼
    # ------------------------------------------------------------------

    def _uid_cache_reverse(self, channel_uid: str) -> str:
        """channelUid로 store_name 역조회."""
        for name, uid in self._uid_cache.items():
            if uid == channel_uid:
                return name
        return ""

    @staticmethod
    def _extract_store_name(url: str) -> Optional[str]:
        """URL에서 스토어명 추출."""
        m = re.search(r"(?:smartstore|brand)\.naver\.com/([a-zA-Z0-9_-]+)", url)
        return m.group(1) if m else None

    @staticmethod
    def _extract_category_id(url: str) -> Optional[str]:
        """URL에서 카테고리 ID 추출. 없으면 None (전체 상품)."""
        m = re.search(r"/category/(\w{8,})", url)
        return m.group(1) if m else None

    @staticmethod
    def _extract_product_id(url: str) -> Optional[str]:
        """URL에서 상품 ID 추출."""
        m = re.search(r"/products/(\d+)", url)
        return m.group(1) if m else None

    @staticmethod
    def _parse_search_url(url: str) -> tuple[bool, Optional[str]]:
        """URL에서 (검색 URL 여부, 키워드) 튜플 반환.

        Returns:
            (False, None) — /search path 없음
            (True, "양말") — /search?q=양말
            (True, None)  — /search?q= (빈 키워드) → 호출부에서 silent 실패 차단 필요
        """
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(url)
        if "/search" not in parsed.path:
            return False, None
        qs = parse_qs(parsed.query)
        kw = qs.get("q", [""])[0].strip()
        return True, (kw or None)
