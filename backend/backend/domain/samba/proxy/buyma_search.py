"""바이마 시세 조회 클라이언트 — 경쟁 셀러 가격 조회 (역방향 소싱 마진 선별용).

품번/키워드로 바이마 검색 결과 HTML을 파싱해 판매가·셀러수를 추출한다.
공식 API 없이 검색 페이지 SSR HTML을 직접 GET (KREAM search 방식과 동일).
로그인 불필요(공개 검색).

용도: 무신사 소싱가 vs 바이마 경쟁가를 비교해 마진 나는 상품만 자동 선별.
  손익공식: 무신사 소싱가 ≤ 바이마 최저가(엔) × 약 6.5원 → 마진.
"""

from __future__ import annotations

import re
import statistics
from typing import Any

import httpx

from backend.utils.logger import logger

# 바이마 품번/키워드 검색 (예: https://www.buyma.com/r/JH7238/)
_SEARCH_URL = "https://www.buyma.com/r/{q}/"

# 엔화 가격 패턴: "¥8,800" 또는 "8,800円"
_YEN_PATTERNS = (
    re.compile(r"¥\s*([0-9][0-9,]{2,})"),
    re.compile(r"([0-9][0-9,]{2,})\s*円"),
)
# 검색 결과 건수: "해당 건수 N 건" / "N件"
_COUNT_PATTERNS = (
    re.compile(r"該当\s*([0-9,]+)\s*件"),
    re.compile(r"([0-9,]+)\s*件"),
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ja,ko;q=0.9",
}

# 신발 판매가 상식 범위(엔) — 노이즈(포인트/할인율/기타 숫자) 제거용
_MIN_YEN = 2000
_MAX_YEN = 300000


class BuymaSearchClient:
    """바이마 공개 검색으로 경쟁 셀러 시세를 조회한다."""

    def __init__(self, *, timeout: float = 20.0) -> None:
        self._timeout = httpx.Timeout(timeout, connect=10.0)

    async def get_market_price(self, query: str) -> dict[str, Any]:
        """품번/키워드로 바이마 시세 요약 조회.

        Returns:
            {
              "query": str,
              "found": bool,
              "count": int,          # 검색 결과 건수(셀러/리스팅 수 근사)
              "min_price": int|None, # 최저 판매가(엔)
              "median_price": int|None,
              "sample": [int, ...],  # 파싱된 가격 표본(정렬)
            }
        """
        url = _SEARCH_URL.format(q=query.strip())
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=True
            ) as client:
                resp = await client.get(url, headers=_HEADERS)
        except Exception as exc:  # 네트워크 오류는 조회 실패로 (영구실패 아님)
            logger.warning(f"[바이마시세] 조회 실패 {query}: {exc}")
            return self._empty(query)

        if resp.status_code != 200:
            logger.warning(f"[바이마시세] HTTP {resp.status_code}: {query}")
            return self._empty(query)

        html = resp.text
        if not html or len(html) < 5000:
            # 차단/빈 응답 의심
            logger.warning(f"[바이마시세] 응답이 너무 짧음(차단 의심): {query}")
            return self._empty(query)

        prices = self._extract_prices(html)
        count = self._extract_count(html)

        if not prices:
            return {**self._empty(query), "count": count}

        prices.sort()
        return {
            "query": query,
            "found": True,
            "count": count or len(prices),
            "min_price": prices[0],
            "median_price": int(statistics.median(prices)),
            "sample": prices[:30],
        }

    # ------------------------------------------------------------------
    # 파싱
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_prices(html: str) -> list[int]:
        found: list[int] = []
        for pat in _YEN_PATTERNS:
            for m in pat.findall(html):
                try:
                    val = int(m.replace(",", ""))
                except ValueError:
                    continue
                if _MIN_YEN <= val <= _MAX_YEN:
                    found.append(val)
        return found

    @staticmethod
    def _extract_count(html: str) -> int:
        for pat in _COUNT_PATTERNS:
            m = pat.search(html)
            if m:
                try:
                    return int(m.group(1).replace(",", ""))
                except ValueError:
                    continue
        return 0

    @staticmethod
    def _empty(query: str) -> dict[str, Any]:
        return {
            "query": query,
            "found": False,
            "count": 0,
            "min_price": None,
            "median_price": None,
            "sample": [],
        }
