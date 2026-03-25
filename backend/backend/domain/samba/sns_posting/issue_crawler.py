"""구글 뉴스 RSS 기반 이슈 크롤러.

카테고리별 키워드로 구글 뉴스 RSS를 검색하고
제목/링크/날짜/요약을 반환한다.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import quote

import httpx

from backend.utils.logger import logger


# 카테고리별 기본 검색 키워드
DEFAULT_CATEGORIES: dict[str, list[str]] = {
    'politics': ['정치', '국회', '대통령', '선거'],
    'economy': ['경제', '주식', '부동산', '금리'],
    'sports': ['축구', '야구', 'NBA', '올림픽'],
    'tech': ['AI', '스마트폰', '테슬라', '반도체'],
    'fashion': ['패션', '코디', '신상', '트렌드'],
    'food': ['레시피', '맛집', '요리', '다이어트'],
    'entertainment': ['드라마', '영화', '아이돌', '예능'],
    'health': ['건강', '운동', '다이어트', '영양제'],
}


def _strip_html(text: str) -> str:
    """HTML 태그 제거."""
    return re.sub(r'<[^>]+>', '', text).strip()


def _dedup_key(title: str) -> str:
    """중복 제거용 키 — 제목 앞 30자, 공백 제거."""
    return re.sub(r'\s+', '', title)[:30]


class IssueCrawler:
    """구글 뉴스 RSS 이슈 검색기."""

    # 구글 뉴스 RSS 엔드포인트 (한국어/한국 리전)
    GOOGLE_NEWS_RSS = (
        'https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko'
    )

    def __init__(self) -> None:
        # 15초 타임아웃, User-Agent 설정
        self._client = httpx.AsyncClient(
            timeout=15,
            headers={
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/124.0.0.0 Safari/537.36'
                ),
                'Accept-Language': 'ko-KR,ko;q=0.9',
            },
            follow_redirects=True,
        )

    async def search_issues(
        self,
        category: str,
        keywords: Optional[list[str]] = None,
        max_results: int = 20,
    ) -> list[dict]:
        """카테고리 키워드로 이슈를 검색하고 중복 제거 후 반환.

        Args:
            category: DEFAULT_CATEGORIES의 키 (예: 'tech')
            keywords: 직접 지정할 키워드 목록. None이면 DEFAULT_CATEGORIES 사용.
            max_results: 최대 반환 건수.

        Returns:
            이슈 딕셔너리 목록 [{'title', 'link', 'pub_date', 'description'}, ...]
        """
        # 키워드 결정
        kw_list = keywords if keywords is not None else DEFAULT_CATEGORIES.get(category, [])
        if not kw_list:
            logger.warning(f'[IssueCrawler] 알 수 없는 카테고리: {category}')
            return []

        # 키워드별 RSS 수집 (중복 포함)
        per_keyword = max(1, max_results // len(kw_list)) + 5
        seen: set[str] = set()
        results: list[dict] = []

        for kw in kw_list:
            if len(results) >= max_results:
                break
            items = await self._fetch_rss(kw, max_per_keyword=per_keyword)
            for item in items:
                key = _dedup_key(item['title'])
                if key in seen:
                    continue
                seen.add(key)
                results.append(item)
                if len(results) >= max_results:
                    break

        logger.info(
            f'[IssueCrawler] category={category} keywords={kw_list} '
            f'결과={len(results)}건'
        )
        return results

    async def _fetch_rss(self, query: str, max_per_keyword: int = 10) -> list[dict]:
        """구글 뉴스 RSS 요청 후 XML 파싱.

        Args:
            query: 검색 쿼리 문자열.
            max_per_keyword: 키워드당 최대 파싱 건수.

        Returns:
            아이템 목록 [{'title', 'link', 'pub_date', 'description'}, ...]
        """
        url = self.GOOGLE_NEWS_RSS.format(query=quote(query))
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.warning(f'[IssueCrawler] HTTP 오류 query={query}: {e}')
            return []
        except httpx.RequestError as e:
            logger.warning(f'[IssueCrawler] 요청 실패 query={query}: {e}')
            return []

        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as e:
            logger.warning(f'[IssueCrawler] XML 파싱 오류 query={query}: {e}')
            return []

        items: list[dict] = []
        # RSS 구조: <rss><channel><item>...</item></channel></rss>
        for item_el in root.findall('./channel/item'):
            title_el = item_el.find('title')
            link_el = item_el.find('link')
            pub_date_el = item_el.find('pubDate')
            desc_el = item_el.find('description')

            title = _strip_html(title_el.text or '') if title_el is not None else ''
            link = (link_el.text or '').strip() if link_el is not None else ''
            pub_date = (pub_date_el.text or '').strip() if pub_date_el is not None else ''

            # description: HTML 태그 제거 후 500자 제한
            raw_desc = desc_el.text or '' if desc_el is not None else ''
            description = _strip_html(raw_desc)[:500]

            if not title:
                continue

            items.append({
                'title': title,
                'link': link,
                'pub_date': pub_date,
                'description': description,
            })

            if len(items) >= max_per_keyword:
                break

        return items

    async def close(self) -> None:
        """httpx 클라이언트 종료."""
        await self._client.aclose()

    # async with 지원
    async def __aenter__(self) -> 'IssueCrawler':
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()
