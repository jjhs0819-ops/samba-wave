# SNS 자동 포스팅 + 도매몰 연동 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 도매몰(도매매/오너클랜) 상품을 소싱하고, 구글 이슈 검색 → AI 글 생성 → 워드프레스 자동 포스팅 + 상품 연동으로 자사몰 유입과 부수익(에드센스/쿠팡파트너스)을 만드는 SNS 마케팅 시스템 구축

**Architecture:** 백엔드에 3개 도메인(wholesale_sourcing, sns_posting, wp_connect) 추가. 도매몰 RSS/웹 크롤링으로 상품 수집 → DB 저장. 구글 뉴스 RSS로 이슈 검색 → Claude API로 SEO 최적화 글 생성 → WordPress REST API로 자동 발행. 프론트 SNS마케팅 탭을 6탭으로 확장.

**Tech Stack:** FastAPI, SQLModel, Claude API (anthropic), WordPress REST API, Google News RSS, httpx, asyncio, Next.js 15, TypeScript

---

## 파일 구조

### 백엔드 — 새로 생성

```
backend/backend/domain/samba/sns_posting/
  __init__.py
  model.py          — WpSite, SnsPost, SnsKeywordGroup, SnsAutoConfig 모델
  service.py         — 이슈 검색, AI 글 생성, WP 발행, 자동 포스팅 오케스트레이션
  repository.py      — CRUD
  wordpress.py       — WordPress REST API 클라이언트
  issue_crawler.py   — 구글 뉴스 RSS 이슈 검색
  ai_writer.py       — Claude API 글 생성 + SEO 최적화

backend/backend/domain/samba/wholesale/
  __init__.py
  model.py           — SambaWholesaleProduct 모델
  service.py         — 도매몰 상품 수집/동기화
  repository.py      — CRUD
  crawler.py         — 도매매/오너클랜 상품 크롤링

backend/backend/api/v1/routers/samba/
  sns_posting.py     — SNS 포스팅 API 라우터
  wholesale.py       — 도매몰 소싱 API 라우터

backend/alembic/versions/
  xxxx_add_sns_posting_tables.py
  xxxx_add_wholesale_tables.py
```

### 프론트엔드 — 수정/생성

```
frontend/src/app/samba/sns/page.tsx           — 6탭 UI 전체 재구성
frontend/src/lib/samba/api.ts                 — snsApi, wholesaleApi 추가
```

### 백엔드 — 수정

```
backend/backend/main.py                       — 신규 라우터 2개 등록
backend/backend/core/config.py                — WP 관련 설정 없음 (DB 저장 방식)
```

---

## Phase 1: 도매몰 소싱 (Task 1~3)

### Task 1: 도매몰 상품 모델 + 마이그레이션

**Files:**
- Create: `backend/backend/domain/samba/wholesale/__init__.py`
- Create: `backend/backend/domain/samba/wholesale/model.py`
- Create: `backend/backend/domain/samba/wholesale/repository.py`

- [ ] **Step 1: 모델 파일 생성**

```python
# model.py
from ulid import ULID
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, String, Text, Integer, Float, JSON, DateTime
from datetime import datetime
from typing import Optional, Any

def generate_ws_id() -> str:
    return f"ws_{ULID()}"

class SambaWholesaleProduct(SQLModel, table=True):
    __tablename__ = "samba_wholesale_product"
    id: str = Field(default_factory=generate_ws_id, primary_key=True, max_length=30)
    tenant_id: Optional[str] = Field(default=None, sa_column=Column(String, index=True, nullable=True))
    source_mall: str = Field(sa_column=Column(String(50), nullable=False))  # domeme, ownerclan
    product_id: str = Field(sa_column=Column(String(100), nullable=False))  # 도매몰 상품 ID
    name: str = Field(sa_column=Column(Text, nullable=False))
    price: int = Field(default=0, sa_column=Column(Integer, nullable=False))  # 도매가
    retail_price: int = Field(default=0, sa_column=Column(Integer))  # 소비자가
    category: Optional[str] = Field(default=None, sa_column=Column(String(200)))
    image_url: Optional[str] = Field(default=None, sa_column=Column(Text))
    detail_url: Optional[str] = Field(default=None, sa_column=Column(Text))
    options: Optional[Any] = Field(default=None, sa_column=Column(JSON))
    stock_status: str = Field(default="in_stock", sa_column=Column(String(20)))
    collected_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime))
```

- [ ] **Step 2: repository.py 생성**

```python
# repository.py
from backend.domain.samba.shared.base_repository import BaseRepository
from .model import SambaWholesaleProduct

class WholesaleProductRepository(BaseRepository[SambaWholesaleProduct]):
    model = SambaWholesaleProduct
```

- [ ] **Step 3: __init__.py 생성**

```python
# __init__.py (빈 파일)
```

- [ ] **Step 4: alembic env.py에 모델 import 추가 + 마이그레이션 생성**

```bash
cd backend
alembic revision --autogenerate -m "add_samba_wholesale_product_table"
alembic upgrade head
```

- [ ] **Step 5: 커밋**

```bash
git add backend/backend/domain/samba/wholesale/ backend/alembic/versions/
git commit -m "도매몰 상품 모델 + 마이그레이션"
```

---

### Task 2: 도매몰 크롤러 + 서비스

**Files:**
- Create: `backend/backend/domain/samba/wholesale/crawler.py`
- Create: `backend/backend/domain/samba/wholesale/service.py`

- [ ] **Step 1: 크롤러 생성 — 도매매 RSS/API 기반**

```python
# crawler.py
import httpx
import xml.etree.ElementTree as ET
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

class WholesaleCrawler:
    """도매몰 상품 크롤러 (도매매/오너클랜)."""

    SOURCES = {
        "domeme": {
            "name": "도매매",
            "base_url": "https://domeggook.com",
            "search_url": "https://domeggook.com/main/item/itemList.php",
        },
        "ownerclan": {
            "name": "오너클랜",
            "base_url": "https://www.ownerclan.com",
            "search_url": "https://www.ownerclan.com/V2/product/productList.html",
        },
    }

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30, follow_redirects=True)

    async def search_products(
        self, source: str, keyword: str, page: int = 1, size: int = 50
    ) -> List[Dict[str, Any]]:
        """키워드 검색으로 도매몰 상품 조회."""
        if source == "domeme":
            return await self._search_domeme(keyword, page, size)
        elif source == "ownerclan":
            return await self._search_ownerclan(keyword, page, size)
        return []

    async def _search_domeme(self, keyword: str, page: int, size: int) -> List[Dict[str, Any]]:
        """도매매 상품 검색."""
        try:
            resp = await self.client.get(
                self.SOURCES["domeme"]["search_url"],
                params={"keyword": keyword, "page": page, "pageSize": size},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            # HTML 파싱 또는 API 응답 처리
            # 실제 구현은 사이트 구조에 맞게 조정 필요
            products = self._parse_product_list(resp.text, "domeme")
            return products
        except Exception as e:
            logger.error(f"도매매 검색 실패: {e}")
            return []

    async def _search_ownerclan(self, keyword: str, page: int, size: int) -> List[Dict[str, Any]]:
        """오너클랜 상품 검색."""
        try:
            resp = await self.client.get(
                self.SOURCES["ownerclan"]["search_url"],
                params={"searchWord": keyword, "page": page},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            products = self._parse_product_list(resp.text, "ownerclan")
            return products
        except Exception as e:
            logger.error(f"오너클랜 검색 실패: {e}")
            return []

    def _parse_product_list(self, html: str, source: str) -> List[Dict[str, Any]]:
        """HTML에서 상품 목록 파싱 (BeautifulSoup 대신 간단 파싱)."""
        # 실제 사이트 구조에 맞게 구현
        # 여기서는 기본 구조만 정의
        return []

    async def close(self):
        await self.client.aclose()
```

- [ ] **Step 2: 서비스 생성**

```python
# service.py
from sqlalchemy.ext.asyncio import AsyncSession
from .model import SambaWholesaleProduct
from .repository import WholesaleProductRepository
from .crawler import WholesaleCrawler
from typing import List, Optional
from datetime import datetime

class WholesaleService:
    """도매몰 상품 소싱 서비스."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = WholesaleProductRepository(session)
        self.crawler = WholesaleCrawler()

    async def search_and_save(
        self, source: str, keyword: str, page: int = 1, tenant_id: Optional[str] = None
    ) -> List[SambaWholesaleProduct]:
        """도매몰 검색 → DB 저장."""
        raw_products = await self.crawler.search_products(source, keyword, page)
        saved = []
        for p in raw_products:
            product = SambaWholesaleProduct(
                tenant_id=tenant_id,
                source_mall=source,
                product_id=p.get("product_id", ""),
                name=p.get("name", ""),
                price=p.get("price", 0),
                retail_price=p.get("retail_price", 0),
                category=p.get("category"),
                image_url=p.get("image_url"),
                detail_url=p.get("detail_url"),
                options=p.get("options"),
            )
            self.session.add(product)
            saved.append(product)
        await self.session.commit()
        return saved

    async def list_products(
        self, source: Optional[str] = None, keyword: Optional[str] = None,
        page: int = 1, size: int = 50, tenant_id: Optional[str] = None
    ) -> List[SambaWholesaleProduct]:
        """저장된 도매몰 상품 조회."""
        from sqlalchemy import select
        stmt = select(SambaWholesaleProduct)
        if tenant_id:
            stmt = stmt.where(SambaWholesaleProduct.tenant_id == tenant_id)
        if source:
            stmt = stmt.where(SambaWholesaleProduct.source_mall == source)
        if keyword:
            stmt = stmt.where(SambaWholesaleProduct.name.contains(keyword))
        stmt = stmt.order_by(SambaWholesaleProduct.collected_at.desc())
        stmt = stmt.offset((page - 1) * size).limit(size)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
```

- [ ] **Step 3: 커밋**

```bash
git add backend/backend/domain/samba/wholesale/
git commit -m "도매몰 크롤러 + 서비스 구현"
```

---

### Task 3: 도매몰 API 라우터

**Files:**
- Create: `backend/backend/api/v1/routers/samba/wholesale.py`
- Modify: `backend/backend/main.py` — 라우터 등록

- [ ] **Step 1: 라우터 생성**

```python
# wholesale.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from backend.db.orm import get_write_session_dependency
from backend.domain.samba.wholesale.service import WholesaleService
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/wholesale", tags=["samba-wholesale"])

class WholesaleSearchRequest(BaseModel):
    source: str  # domeme, ownerclan
    keyword: str
    page: int = 1

@router.post("/search")
async def search_wholesale(
    req: WholesaleSearchRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """도매몰 상품 검색 + 저장."""
    svc = WholesaleService(session)
    products = await svc.search_and_save(req.source, req.keyword, req.page)
    return {"count": len(products), "products": [p.model_dump() for p in products]}

@router.get("/products")
async def list_wholesale_products(
    source: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    size: int = 50,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """저장된 도매몰 상품 조회."""
    svc = WholesaleService(session)
    products = await svc.list_products(source, keyword, page, size)
    return [p.model_dump() for p in products]
```

- [ ] **Step 2: main.py에 라우터 등록**

```python
from backend.api.v1.routers.samba.wholesale import router as samba_wholesale_router
# ...
app.include_router(samba_wholesale_router, prefix="/api/v1/samba")
```

- [ ] **Step 3: 커밋**

```bash
git add backend/backend/api/v1/routers/samba/wholesale.py backend/backend/main.py
git commit -m "도매몰 소싱 API 라우터"
```

---

## Phase 2: SNS 자동 포스팅 시스템 (Task 4~8)

### Task 4: SNS 포스팅 모델 + 마이그레이션

**Files:**
- Create: `backend/backend/domain/samba/sns_posting/__init__.py`
- Create: `backend/backend/domain/samba/sns_posting/model.py`
- Create: `backend/backend/domain/samba/sns_posting/repository.py`

- [ ] **Step 1: 모델 파일 생성**

```python
# model.py
from ulid import ULID
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, String, Text, Integer, Boolean, JSON, DateTime
from datetime import datetime
from typing import Optional, Any

def gen_wp_id() -> str:
    return f"wp_{ULID()}"

def gen_post_id() -> str:
    return f"snp_{ULID()}"

def gen_kg_id() -> str:
    return f"skg_{ULID()}"

def gen_ac_id() -> str:
    return f"sac_{ULID()}"

class SambaWpSite(SQLModel, table=True):
    """워드프레스 사이트 연결 정보."""
    __tablename__ = "samba_wp_site"
    id: str = Field(default_factory=gen_wp_id, primary_key=True, max_length=30)
    tenant_id: Optional[str] = Field(default=None, sa_column=Column(String, index=True))
    site_url: str = Field(sa_column=Column(Text, nullable=False))
    username: str = Field(sa_column=Column(String(100), nullable=False))
    app_password: str = Field(sa_column=Column(Text, nullable=False))
    site_name: Optional[str] = Field(default=None, sa_column=Column(String(200)))
    status: str = Field(default="active", sa_column=Column(String(20)))
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime))

class SambaSnKeywordGroup(SQLModel, table=True):
    """이슈 검색 키워드 그룹."""
    __tablename__ = "samba_sns_keyword_group"
    id: str = Field(default_factory=gen_kg_id, primary_key=True, max_length=30)
    tenant_id: Optional[str] = Field(default=None, sa_column=Column(String, index=True))
    name: str = Field(sa_column=Column(String(100), nullable=False))  # 그룹명: 정치, 경제 등
    category: str = Field(sa_column=Column(String(50), nullable=False))  # politics, economy 등
    keywords: Any = Field(default=[], sa_column=Column(JSON))  # 세부 키워드 리스트
    is_active: bool = Field(default=True, sa_column=Column(Boolean))
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime))

class SambaSnsPost(SQLModel, table=True):
    """SNS 포스팅 이력."""
    __tablename__ = "samba_sns_post"
    id: str = Field(default_factory=gen_post_id, primary_key=True, max_length=30)
    tenant_id: Optional[str] = Field(default=None, sa_column=Column(String, index=True))
    wp_site_id: Optional[str] = Field(default=None, sa_column=Column(String(30)))
    wp_post_id: Optional[int] = Field(default=None, sa_column=Column(Integer))
    title: str = Field(sa_column=Column(Text, nullable=False))
    content: Optional[str] = Field(default=None, sa_column=Column(Text))
    category: Optional[str] = Field(default=None, sa_column=Column(String(100)))
    keyword: Optional[str] = Field(default=None, sa_column=Column(String(200)))
    source_url: Optional[str] = Field(default=None, sa_column=Column(Text))
    status: str = Field(default="draft", sa_column=Column(String(20)))  # draft, published, failed
    language: str = Field(default="ko", sa_column=Column(String(5)))
    product_ids: Optional[Any] = Field(default=None, sa_column=Column(JSON))  # 연결 상품 ID
    published_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime))
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime))

class SambaSnsAutoConfig(SQLModel, table=True):
    """자동 포스팅 설정."""
    __tablename__ = "samba_sns_auto_config"
    id: str = Field(default_factory=gen_ac_id, primary_key=True, max_length=30)
    tenant_id: Optional[str] = Field(default=None, sa_column=Column(String, index=True))
    wp_site_id: str = Field(sa_column=Column(String(30), nullable=False))
    interval_minutes: int = Field(default=20, sa_column=Column(Integer))
    max_daily_posts: int = Field(default=150, sa_column=Column(Integer))
    is_running: bool = Field(default=False, sa_column=Column(Boolean))
    language: str = Field(default="ko", sa_column=Column(String(5)))
    include_product_banner: bool = Field(default=True, sa_column=Column(Boolean))
    product_banner_html: Optional[str] = Field(default=None, sa_column=Column(Text))
    today_count: int = Field(default=0, sa_column=Column(Integer))
    last_posted_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime))
```

- [ ] **Step 2: repository.py 생성**

```python
# repository.py
from backend.domain.samba.shared.base_repository import BaseRepository
from .model import SambaWpSite, SambaSnKeywordGroup, SambaSnsPost, SambaSnsAutoConfig

class WpSiteRepository(BaseRepository[SambaWpSite]):
    model = SambaWpSite

class SnsKeywordGroupRepository(BaseRepository[SambaSnKeywordGroup]):
    model = SambaSnKeywordGroup

class SnsPostRepository(BaseRepository[SambaSnsPost]):
    model = SambaSnsPost

class SnsAutoConfigRepository(BaseRepository[SambaSnsAutoConfig]):
    model = SambaSnsAutoConfig
```

- [ ] **Step 3: 마이그레이션 생성 + 적용**

```bash
cd backend
alembic revision --autogenerate -m "add_sns_posting_tables"
alembic upgrade head
```

- [ ] **Step 4: 커밋**

```bash
git add backend/backend/domain/samba/sns_posting/ backend/alembic/versions/
git commit -m "SNS 포스팅 모델 4개 테이블 + 마이그레이션"
```

---

### Task 5: 구글 뉴스 이슈 크롤러

**Files:**
- Create: `backend/backend/domain/samba/sns_posting/issue_crawler.py`

- [ ] **Step 1: 이슈 크롤러 구현**

```python
# issue_crawler.py
"""구글 뉴스 RSS 기반 이슈 검색기."""
import httpx
import xml.etree.ElementTree as ET
from typing import List, Dict
from urllib.parse import quote
import logging
import re
from html import unescape

logger = logging.getLogger(__name__)

# 카테고리별 기본 키워드
DEFAULT_CATEGORIES = {
    "politics": {"name": "정치", "keywords": ["정치", "국회", "대통령", "선거"]},
    "economy": {"name": "경제", "keywords": ["경제", "주식", "부동산", "금리"]},
    "sports": {"name": "스포츠", "keywords": ["축구", "야구", "NBA", "올림픽"]},
    "tech": {"name": "IT/기술", "keywords": ["AI", "스마트폰", "테슬라", "반도체"]},
    "fashion": {"name": "패션", "keywords": ["패션", "코디", "신상", "트렌드"]},
    "food": {"name": "음식/레시피", "keywords": ["레시피", "맛집", "요리", "다이어트"]},
    "entertainment": {"name": "연예", "keywords": ["드라마", "영화", "아이돌", "예능"]},
    "health": {"name": "건강", "keywords": ["건강", "운동", "다이어트", "영양제"]},
}

class IssueCrawler:
    """구글 뉴스 RSS에서 카테고리별 이슈 검색."""

    GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=15, follow_redirects=True)

    async def search_issues(
        self, category: str, keywords: List[str] | None = None, max_results: int = 20
    ) -> List[Dict]:
        """카테고리 키워드로 구글 뉴스 이슈 검색."""
        if not keywords:
            cat_info = DEFAULT_CATEGORIES.get(category, {})
            keywords = cat_info.get("keywords", [category])

        all_issues = []
        for kw in keywords:
            try:
                issues = await self._fetch_rss(kw, max_per_keyword=max_results // len(keywords) + 1)
                all_issues.extend(issues)
            except Exception as e:
                logger.warning(f"이슈 검색 실패 [{kw}]: {e}")

        # 중복 제거 (제목 기준)
        seen = set()
        unique = []
        for issue in all_issues:
            title_key = re.sub(r'\s+', '', issue["title"])[:30]
            if title_key not in seen:
                seen.add(title_key)
                unique.append(issue)

        return unique[:max_results]

    async def _fetch_rss(self, query: str, max_per_keyword: int = 10) -> List[Dict]:
        """구글 뉴스 RSS에서 이슈 파싱."""
        url = self.GOOGLE_NEWS_RSS.format(query=quote(query))
        resp = await self.client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        items = root.findall(".//item")
        results = []

        for item in items[:max_per_keyword]:
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            description = unescape(item.findtext("description", ""))
            # HTML 태그 제거
            description = re.sub(r'<[^>]+>', '', description).strip()

            results.append({
                "title": title,
                "link": link,
                "pub_date": pub_date,
                "description": description[:500],
                "keyword": query,
            })

        return results

    async def close(self):
        await self.client.aclose()
```

- [ ] **Step 2: 커밋**

```bash
git add backend/backend/domain/samba/sns_posting/issue_crawler.py
git commit -m "구글 뉴스 RSS 이슈 크롤러"
```

---

### Task 6: AI 글 생성기 (Claude API)

**Files:**
- Create: `backend/backend/domain/samba/sns_posting/ai_writer.py`

- [ ] **Step 1: AI 글 생성기 구현**

```python
# ai_writer.py
"""Claude API 기반 SEO 최적화 블로그 글 생성기."""
import anthropic
from backend.core.config import settings
from typing import Optional, List, Dict
import logging
import json

logger = logging.getLogger(__name__)

class AiWriter:
    """Claude API로 SEO 최적화 블로그 글 생성."""

    def __init__(self):
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def generate_post(
        self,
        issue_title: str,
        issue_description: str,
        category: str,
        language: str = "ko",
        product_info: Optional[Dict] = None,
        word_count: int = 1500,
    ) -> Dict:
        """이슈 기반 블로그 글 생성.

        Returns:
            {"title": str, "content": str, "tags": list, "excerpt": str, "category": str}
        """
        lang_instruction = "한국어로 작성" if language == "ko" else "Write in English"

        product_section = ""
        if product_info:
            product_section = f"""
추가로, 글 하단에 자연스럽게 아래 상품을 추천하는 섹션을 넣어주세요:
- 상품명: {product_info.get('name', '')}
- 가격: {product_info.get('price', '')}원
- 링크: {product_info.get('url', '')}
"""

        prompt = f"""당신은 전문 블로거입니다. 아래 뉴스 이슈를 바탕으로 SEO에 최적화된 블로그 글을 작성해주세요.

## 이슈 정보
- 제목: {issue_title}
- 요약: {issue_description}
- 카테고리: {category}

## 작성 규칙
- {lang_instruction}
- {word_count}자 이상 작성
- H2, H3 소제목 활용 (HTML 태그 사용)
- 첫 문단에 핵심 키워드 포함 (SEO)
- 자연스럽고 읽기 쉬운 문체
- 중복 내용 없이 깊이 있는 분석
- 마지막에 "마치며" 또는 "정리" 섹션 포함
{product_section}

## 출력 형식 (JSON)
{{"title": "SEO 최적화된 제목 (60자 이내)", "content": "HTML 본문", "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"], "excerpt": "요약 (150자)", "category": "{category}"}}

JSON만 출력하세요. 다른 텍스트 없이."""

        try:
            response = await self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            # JSON 파싱 (마크다운 코드블록 제거)
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except Exception as e:
            logger.error(f"AI 글 생성 실패: {e}")
            return {
                "title": issue_title,
                "content": f"<p>{issue_description}</p>",
                "tags": [category],
                "excerpt": issue_description[:150],
                "category": category,
            }

    async def generate_image_prompt(self, title: str, category: str) -> str:
        """블로그 대표 이미지용 프롬프트 생성."""
        try:
            response = await self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{"role": "user", "content": f"Generate a short, vivid image prompt (in English, max 50 words) for a blog post titled '{title}' in category '{category}'. No text in image. Modern, clean style."}],
            )
            return response.content[0].text.strip()
        except Exception:
            return f"Modern illustration about {category}, clean design, no text"
```

- [ ] **Step 2: 커밋**

```bash
git add backend/backend/domain/samba/sns_posting/ai_writer.py
git commit -m "Claude API 기반 AI 글 생성기"
```

---

### Task 7: WordPress REST API 클라이언트

**Files:**
- Create: `backend/backend/domain/samba/sns_posting/wordpress.py`

- [ ] **Step 1: WP 클라이언트 구현**

```python
# wordpress.py
"""WordPress REST API 클라이언트."""
import httpx
import base64
from typing import Dict, Optional, List
import logging

logger = logging.getLogger(__name__)

class WordPressClient:
    """WordPress REST API v2 클라이언트.

    인증: Application Password (Basic Auth)
    """

    def __init__(self, site_url: str, username: str, app_password: str):
        self.site_url = site_url.rstrip("/")
        self.api_url = f"{self.site_url}/wp-json/wp/v2"
        credentials = base64.b64encode(f"{username}:{app_password}".encode()).decode()
        self.client = httpx.AsyncClient(
            timeout=30,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/json",
            },
        )

    async def test_connection(self) -> Dict:
        """연결 테스트 — 사이트 정보 반환."""
        try:
            resp = await self.client.get(f"{self.site_url}/wp-json")
            resp.raise_for_status()
            data = resp.json()
            return {"ok": True, "name": data.get("name", ""), "url": data.get("url", "")}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def create_post(
        self,
        title: str,
        content: str,
        status: str = "publish",
        categories: Optional[List[int]] = None,
        tags: Optional[List[str]] = None,
        excerpt: Optional[str] = None,
        featured_media: Optional[int] = None,
    ) -> Dict:
        """새 글 발행."""
        payload = {
            "title": title,
            "content": content,
            "status": status,
        }
        if categories:
            payload["categories"] = categories
        if tags:
            # 태그는 ID가 아닌 이름으로 전송 (WP가 자동 생성)
            tag_ids = await self._ensure_tags(tags)
            payload["tags"] = tag_ids
        if excerpt:
            payload["excerpt"] = excerpt
        if featured_media:
            payload["featured_media"] = featured_media

        resp = await self.client.post(f"{self.api_url}/posts", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return {"id": data["id"], "link": data["link"], "status": data["status"]}

    async def get_or_create_category(self, name: str) -> int:
        """카테고리 조회 또는 생성 → ID 반환."""
        # 기존 카테고리 검색
        resp = await self.client.get(f"{self.api_url}/categories", params={"search": name})
        cats = resp.json()
        for cat in cats:
            if cat["name"].lower() == name.lower():
                return cat["id"]
        # 없으면 생성
        resp = await self.client.post(f"{self.api_url}/categories", json={"name": name})
        return resp.json()["id"]

    async def _ensure_tags(self, tag_names: List[str]) -> List[int]:
        """태그 이름 → ID 변환 (없으면 생성)."""
        tag_ids = []
        for name in tag_names[:10]:  # 최대 10개
            try:
                resp = await self.client.get(f"{self.api_url}/tags", params={"search": name})
                tags = resp.json()
                found = next((t for t in tags if t["name"].lower() == name.lower()), None)
                if found:
                    tag_ids.append(found["id"])
                else:
                    resp = await self.client.post(f"{self.api_url}/tags", json={"name": name})
                    tag_ids.append(resp.json()["id"])
            except Exception:
                pass
        return tag_ids

    async def upload_media(self, image_bytes: bytes, filename: str) -> Optional[int]:
        """이미지 업로드 → media ID 반환."""
        try:
            resp = await self.client.post(
                f"{self.api_url}/media",
                content=image_bytes,
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                    "Content-Type": "image/jpeg",
                },
            )
            resp.raise_for_status()
            return resp.json()["id"]
        except Exception as e:
            logger.error(f"미디어 업로드 실패: {e}")
            return None

    async def close(self):
        await self.client.aclose()
```

- [ ] **Step 2: 커밋**

```bash
git add backend/backend/domain/samba/sns_posting/wordpress.py
git commit -m "WordPress REST API 클라이언트"
```

---

### Task 8: 자동 포스팅 서비스 + API 라우터

**Files:**
- Create: `backend/backend/domain/samba/sns_posting/service.py`
- Create: `backend/backend/api/v1/routers/samba/sns_posting.py`
- Modify: `backend/backend/main.py` — 라우터 등록

- [ ] **Step 1: 포스팅 서비스 구현**

```python
# service.py
"""SNS 자동 포스팅 오케스트레이션 서비스."""
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from .model import SambaWpSite, SambaSnKeywordGroup, SambaSnsPost, SambaSnsAutoConfig
from .wordpress import WordPressClient
from .issue_crawler import IssueCrawler
from .ai_writer import AiWriter
from typing import Optional, List, Dict, AsyncGenerator
from datetime import datetime, timedelta
import logging
import json

logger = logging.getLogger(__name__)

# 자동 포스팅 태스크 관리
_auto_tasks: Dict[str, asyncio.Task] = {}

class SnsPostingService:
    """SNS 자동 포스팅 서비스."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.crawler = IssueCrawler()
        self.writer = AiWriter()

    # ── WP 사이트 관리 ──

    async def connect_wp(self, site_url: str, username: str, app_password: str, tenant_id: Optional[str] = None) -> Dict:
        """워드프레스 사이트 연결 + 테스트."""
        wp = WordPressClient(site_url, username, app_password)
        result = await wp.test_connection()
        await wp.close()

        if not result["ok"]:
            return {"success": False, "error": result["error"]}

        site = SambaWpSite(
            tenant_id=tenant_id,
            site_url=site_url,
            username=username,
            app_password=app_password,
            site_name=result.get("name", ""),
        )
        self.session.add(site)
        await self.session.commit()
        await self.session.refresh(site)
        return {"success": True, "site": site.model_dump()}

    async def list_wp_sites(self, tenant_id: Optional[str] = None) -> List[SambaWpSite]:
        stmt = select(SambaWpSite)
        if tenant_id:
            stmt = stmt.where(SambaWpSite.tenant_id == tenant_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ── 키워드 그룹 관리 ──

    async def save_keyword_group(self, name: str, category: str, keywords: List[str], tenant_id: Optional[str] = None) -> SambaSnKeywordGroup:
        group = SambaSnKeywordGroup(tenant_id=tenant_id, name=name, category=category, keywords=keywords)
        self.session.add(group)
        await self.session.commit()
        await self.session.refresh(group)
        return group

    async def list_keyword_groups(self, tenant_id: Optional[str] = None) -> List[SambaSnKeywordGroup]:
        stmt = select(SambaSnKeywordGroup)
        if tenant_id:
            stmt = stmt.where(SambaSnKeywordGroup.tenant_id == tenant_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ── 이슈 검색 ──

    async def search_issues(self, category: str, keywords: Optional[List[str]] = None) -> List[Dict]:
        return await self.crawler.search_issues(category, keywords)

    # ── 글 생성 + 발행 ──

    async def generate_and_publish(
        self,
        wp_site_id: str,
        issue: Dict,
        category: str,
        language: str = "ko",
        product_info: Optional[Dict] = None,
        product_banner_html: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Dict:
        """이슈 → AI 글 생성 → WP 발행."""
        # 1. WP 사이트 정보 조회
        site = await self.session.get(SambaWpSite, wp_site_id)
        if not site:
            return {"success": False, "error": "WP 사이트를 찾을 수 없습니다"}

        # 2. AI 글 생성
        generated = await self.writer.generate_post(
            issue_title=issue["title"],
            issue_description=issue.get("description", ""),
            category=category,
            language=language,
            product_info=product_info,
        )

        content = generated["content"]

        # 3. 상품 배너 삽입
        if product_banner_html:
            content += f"\n\n{product_banner_html}"

        # 4. WP 발행
        wp = WordPressClient(site.site_url, site.username, site.app_password)
        try:
            cat_id = await wp.get_or_create_category(generated.get("category", category))
            result = await wp.create_post(
                title=generated["title"],
                content=content,
                categories=[cat_id],
                tags=generated.get("tags", []),
                excerpt=generated.get("excerpt"),
            )
        except Exception as e:
            # 실패 기록
            post = SambaSnsPost(
                tenant_id=tenant_id, wp_site_id=wp_site_id,
                title=generated["title"], content=content,
                category=category, keyword=issue.get("keyword"),
                status="failed", language=language,
            )
            self.session.add(post)
            await self.session.commit()
            return {"success": False, "error": str(e)}
        finally:
            await wp.close()

        # 5. 성공 기록
        post = SambaSnsPost(
            tenant_id=tenant_id, wp_site_id=wp_site_id,
            wp_post_id=result["id"],
            title=generated["title"], content=content,
            category=category, keyword=issue.get("keyword"),
            source_url=issue.get("link"),
            status="published", language=language,
            published_at=datetime.utcnow(),
        )
        self.session.add(post)
        await self.session.commit()
        return {"success": True, "post_id": result["id"], "link": result["link"], "title": generated["title"]}

    # ── 자동 포스팅 SSE 스트리밍 ──

    async def auto_posting_stream(
        self,
        wp_site_id: str,
        tenant_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """자동 포스팅 실행 — SSE 스트리밍."""
        # 설정 조회
        stmt = select(SambaSnsAutoConfig).where(SambaSnsAutoConfig.wp_site_id == wp_site_id)
        result = await self.session.execute(stmt)
        config = result.scalar_one_or_none()
        if not config:
            yield self._sse("error", {"message": "자동 포스팅 설정이 없습니다"})
            return

        # 활성 키워드 그룹 조회
        stmt = select(SambaSnKeywordGroup).where(SambaSnKeywordGroup.is_active == True)
        if tenant_id:
            stmt = stmt.where(SambaSnKeywordGroup.tenant_id == tenant_id)
        result = await self.session.execute(stmt)
        groups = list(result.scalars().all())

        if not groups:
            yield self._sse("error", {"message": "활성화된 키워드 그룹이 없습니다"})
            return

        config.is_running = True
        config.today_count = 0
        await self.session.commit()

        yield self._sse("log", {"message": f"자동 포스팅 시작 — {len(groups)}개 키워드 그룹"})

        posted = 0
        for group in groups:
            if posted >= config.max_daily_posts:
                break

            yield self._sse("log", {"message": f"[{group.name}] 이슈 검색 중..."})
            issues = await self.crawler.search_issues(group.category, group.keywords, max_results=10)
            yield self._sse("log", {"message": f"[{group.name}] {len(issues)}개 이슈 발견"})

            for issue in issues:
                if posted >= config.max_daily_posts:
                    break
                try:
                    result = await self.generate_and_publish(
                        wp_site_id=wp_site_id,
                        issue=issue,
                        category=group.name,
                        language=config.language,
                        product_banner_html=config.product_banner_html,
                        tenant_id=tenant_id,
                    )
                    posted += 1
                    if result["success"]:
                        yield self._sse("success", {
                            "message": f"[{group.name}] 발행 성공: {result['title'][:40]}",
                            "count": posted,
                            "link": result.get("link"),
                        })
                    else:
                        yield self._sse("fail", {"message": f"[{group.name}] 발행 실패: {result.get('error', '')}"})
                except Exception as e:
                    yield self._sse("fail", {"message": f"오류: {str(e)[:100]}"})

                await asyncio.sleep(config.interval_minutes)  # 요청 간 대기 (초 단위)

        config.is_running = False
        config.today_count = posted
        config.last_posted_at = datetime.utcnow()
        await self.session.commit()

        yield self._sse("done", {"message": f"자동 포스팅 완료 — 총 {posted}건 발행", "total": posted})

    # ── 포스팅 이력 조회 ──

    async def list_posts(
        self, page: int = 1, size: int = 50, status: Optional[str] = None, tenant_id: Optional[str] = None
    ) -> List[SambaSnsPost]:
        stmt = select(SambaSnsPost)
        if tenant_id:
            stmt = stmt.where(SambaSnsPost.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(SambaSnsPost.status == status)
        stmt = stmt.order_by(SambaSnsPost.created_at.desc()).offset((page - 1) * size).limit(size)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_dashboard(self, tenant_id: Optional[str] = None) -> Dict:
        """대시보드 데이터."""
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        # 오늘 포스팅 수
        stmt = select(func.count()).select_from(SambaSnsPost).where(SambaSnsPost.created_at >= today)
        if tenant_id:
            stmt = stmt.where(SambaSnsPost.tenant_id == tenant_id)
        today_count = (await self.session.execute(stmt)).scalar() or 0

        # 전체 포스팅 수
        stmt = select(func.count()).select_from(SambaSnsPost)
        if tenant_id:
            stmt = stmt.where(SambaSnsPost.tenant_id == tenant_id)
        total_count = (await self.session.execute(stmt)).scalar() or 0

        # 성공률
        stmt = select(func.count()).select_from(SambaSnsPost).where(SambaSnsPost.status == "published")
        if tenant_id:
            stmt = stmt.where(SambaSnsPost.tenant_id == tenant_id)
        success_count = (await self.session.execute(stmt)).scalar() or 0

        # 자동 포스팅 상태
        stmt = select(SambaSnsAutoConfig)
        if tenant_id:
            stmt = stmt.where(SambaSnsAutoConfig.tenant_id == tenant_id)
        result = await self.session.execute(stmt)
        configs = list(result.scalars().all())
        is_running = any(c.is_running for c in configs)

        return {
            "today_posts": today_count,
            "total_posts": total_count,
            "success_count": success_count,
            "success_rate": round(success_count / total_count * 100, 1) if total_count > 0 else 0,
            "is_running": is_running,
        }

    def _sse(self, event: str, data: Dict) -> str:
        return f"data: {json.dumps({**data, 'event': event}, ensure_ascii=False)}\n\n"
```

- [ ] **Step 2: API 라우터 구현**

```python
# sns_posting.py
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from backend.db.orm import get_write_session_dependency
from backend.domain.samba.sns_posting.service import SnsPostingService
from backend.domain.samba.sns_posting.model import SambaSnsAutoConfig
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter(prefix="/sns", tags=["samba-sns-posting"])

class WpConnectRequest(BaseModel):
    site_url: str
    username: str
    app_password: str

class KeywordGroupRequest(BaseModel):
    name: str
    category: str
    keywords: List[str]

class IssueSearchRequest(BaseModel):
    category: str
    keywords: Optional[List[str]] = None

class PublishRequest(BaseModel):
    wp_site_id: str
    issue: dict
    category: str
    language: str = "ko"
    product_info: Optional[dict] = None

class AutoConfigRequest(BaseModel):
    wp_site_id: str
    interval_minutes: int = 20
    max_daily_posts: int = 150
    language: str = "ko"
    include_product_banner: bool = True
    product_banner_html: Optional[str] = None

# ── WP 사이트 ──

@router.post("/wordpress/connect")
async def connect_wordpress(req: WpConnectRequest, session: AsyncSession = Depends(get_write_session_dependency)):
    svc = SnsPostingService(session)
    return await svc.connect_wp(req.site_url, req.username, req.app_password)

@router.get("/wordpress/sites")
async def list_wp_sites(session: AsyncSession = Depends(get_write_session_dependency)):
    svc = SnsPostingService(session)
    sites = await svc.list_wp_sites()
    return [s.model_dump() for s in sites]

# ── 키워드 그룹 ──

@router.post("/keywords")
async def create_keyword_group(req: KeywordGroupRequest, session: AsyncSession = Depends(get_write_session_dependency)):
    svc = SnsPostingService(session)
    group = await svc.save_keyword_group(req.name, req.category, req.keywords)
    return group.model_dump()

@router.get("/keywords")
async def list_keyword_groups(session: AsyncSession = Depends(get_write_session_dependency)):
    svc = SnsPostingService(session)
    groups = await svc.list_keyword_groups()
    return [g.model_dump() for g in groups]

@router.delete("/keywords/{group_id}")
async def delete_keyword_group(group_id: str, session: AsyncSession = Depends(get_write_session_dependency)):
    from backend.domain.samba.sns_posting.model import SambaSnKeywordGroup
    group = await session.get(SambaSnKeywordGroup, group_id)
    if group:
        await session.delete(group)
        await session.commit()
    return {"ok": True}

# ── 이슈 검색 ──

@router.post("/issue-search")
async def search_issues(req: IssueSearchRequest, session: AsyncSession = Depends(get_write_session_dependency)):
    svc = SnsPostingService(session)
    issues = await svc.search_issues(req.category, req.keywords)
    return issues

# ── 글 생성 + 발행 ──

@router.post("/publish")
async def publish_post(req: PublishRequest, session: AsyncSession = Depends(get_write_session_dependency)):
    svc = SnsPostingService(session)
    return await svc.generate_and_publish(
        wp_site_id=req.wp_site_id, issue=req.issue,
        category=req.category, language=req.language,
        product_info=req.product_info,
    )

# ── 자동 포스팅 ──

@router.post("/auto-posting/config")
async def save_auto_config(req: AutoConfigRequest, session: AsyncSession = Depends(get_write_session_dependency)):
    config = SambaSnsAutoConfig(
        wp_site_id=req.wp_site_id,
        interval_minutes=req.interval_minutes,
        max_daily_posts=req.max_daily_posts,
        language=req.language,
        include_product_banner=req.include_product_banner,
        product_banner_html=req.product_banner_html,
    )
    session.add(config)
    await session.commit()
    await session.refresh(config)
    return config.model_dump()

@router.post("/auto-posting/start/{wp_site_id}")
async def start_auto_posting(wp_site_id: str, session: AsyncSession = Depends(get_write_session_dependency)):
    svc = SnsPostingService(session)
    return StreamingResponse(svc.auto_posting_stream(wp_site_id), media_type="text/event-stream")

@router.post("/auto-posting/stop/{wp_site_id}")
async def stop_auto_posting(wp_site_id: str, session: AsyncSession = Depends(get_write_session_dependency)):
    from sqlalchemy import select, update
    from backend.domain.samba.sns_posting.model import SambaSnsAutoConfig
    stmt = update(SambaSnsAutoConfig).where(SambaSnsAutoConfig.wp_site_id == wp_site_id).values(is_running=False)
    await session.execute(stmt)
    await session.commit()
    return {"ok": True}

# ── 이력 + 대시보드 ──

@router.get("/posts")
async def list_posts(page: int = 1, size: int = 50, status: Optional[str] = None, session: AsyncSession = Depends(get_write_session_dependency)):
    svc = SnsPostingService(session)
    posts = await svc.list_posts(page, size, status)
    return [p.model_dump() for p in posts]

@router.get("/dashboard")
async def get_dashboard(session: AsyncSession = Depends(get_write_session_dependency)):
    svc = SnsPostingService(session)
    return await svc.get_dashboard()
```

- [ ] **Step 3: main.py에 라우터 등록**

```python
from backend.api.v1.routers.samba.sns_posting import router as samba_sns_posting_router
# ...
app.include_router(samba_sns_posting_router, prefix="/api/v1/samba")
```

- [ ] **Step 4: 커밋**

```bash
git add backend/backend/domain/samba/sns_posting/service.py backend/backend/api/v1/routers/samba/sns_posting.py backend/backend/main.py
git commit -m "자동 포스팅 서비스 + SNS API 라우터"
```

---

## Phase 3: 프론트엔드 (Task 9~10)

### Task 9: API 클라이언트 추가

**Files:**
- Modify: `frontend/src/lib/samba/api.ts` — snsApi, wholesaleApi 추가

- [ ] **Step 1: api.ts에 SNS/도매몰 API 추가**

```typescript
// api.ts 하단에 추가

export const snsApi = {
  // WP 사이트
  connectWp: (data: { site_url: string; username: string; app_password: string }) =>
    request(`${SAMBA_PREFIX}/sns/wordpress/connect`, { method: 'POST', body: JSON.stringify(data) }),
  listWpSites: () => request(`${SAMBA_PREFIX}/sns/wordpress/sites`),

  // 키워드 그룹
  createKeywordGroup: (data: { name: string; category: string; keywords: string[] }) =>
    request(`${SAMBA_PREFIX}/sns/keywords`, { method: 'POST', body: JSON.stringify(data) }),
  listKeywordGroups: () => request(`${SAMBA_PREFIX}/sns/keywords`),
  deleteKeywordGroup: (id: string) =>
    request(`${SAMBA_PREFIX}/sns/keywords/${id}`, { method: 'DELETE' }),

  // 이슈 검색
  searchIssues: (data: { category: string; keywords?: string[] }) =>
    request(`${SAMBA_PREFIX}/sns/issue-search`, { method: 'POST', body: JSON.stringify(data) }),

  // 발행
  publish: (data: { wp_site_id: string; issue: Record<string, string>; category: string; language?: string }) =>
    request(`${SAMBA_PREFIX}/sns/publish`, { method: 'POST', body: JSON.stringify(data) }),

  // 자동 포스팅
  saveAutoConfig: (data: { wp_site_id: string; interval_minutes?: number; max_daily_posts?: number; language?: string; product_banner_html?: string }) =>
    request(`${SAMBA_PREFIX}/sns/auto-posting/config`, { method: 'POST', body: JSON.stringify(data) }),
  startAutoPosting: (wpSiteId: string) => `${SAMBA_PREFIX}/sns/auto-posting/start/${wpSiteId}`,  // SSE URL
  stopAutoPosting: (wpSiteId: string) =>
    request(`${SAMBA_PREFIX}/sns/auto-posting/stop/${wpSiteId}`, { method: 'POST' }),

  // 이력 + 대시보드
  listPosts: (page?: number, status?: string) =>
    request(`${SAMBA_PREFIX}/sns/posts?page=${page || 1}${status ? `&status=${status}` : ''}`),
  getDashboard: () => request(`${SAMBA_PREFIX}/sns/dashboard`),
}

export const wholesaleApi = {
  search: (data: { source: string; keyword: string; page?: number }) =>
    request(`${SAMBA_PREFIX}/wholesale/search`, { method: 'POST', body: JSON.stringify(data) }),
  listProducts: (source?: string, keyword?: string, page?: number) =>
    request(`${SAMBA_PREFIX}/wholesale/products?${new URLSearchParams({ ...(source && { source }), ...(keyword && { keyword }), page: String(page || 1) }).toString()}`),
}
```

- [ ] **Step 2: 커밋**

```bash
git add frontend/src/lib/samba/api.ts
git commit -m "SNS/도매몰 API 클라이언트 추가"
```

---

### Task 10: SNS 마케팅 페이지 전체 재구성

**Files:**
- Modify: `frontend/src/app/samba/sns/page.tsx` — 6탭 UI 전체 재구성

**핵심 탭 구조:**

1. **종합현황** — KPI 카드 (오늘 포스팅, 전체 포스팅, 성공률, 자동화 상태) + 최근 포스팅 리스트
2. **자동 포스팅** — WP 연결 + 키워드 그룹 관리 + 시작/중지 + 실시간 로그 (SSE)
3. **게시물 관리** — 포스팅 이력 테이블 (성공/실패 필터)
4. **상품 연동** — 도매몰 상품 검색 + 배너 HTML 설정
5. **수익 대시보드** — 에드센스/쿠팡파트너스 연동 안내
6. **채널 설정** — WP 사이트 관리

- [ ] **Step 1: page.tsx 전체 재구성**

> 파일이 크므로 구현 시 실제 작성. 핵심 컴포넌트:
> - `OverviewTab`: KPI + 최근 포스팅
> - `AutoPostingTab`: WP 연결 폼 + 키워드 관리 + SSE 로그
> - `PostsTab`: 이력 테이블
> - `ProductLinkTab`: 도매몰 검색 + 배너 설정
> - `RevenueTab`: 수익 안내
> - `ChannelSettingsTab`: WP 사이트 목록

- [ ] **Step 2: 커밋**

```bash
git add frontend/src/app/samba/sns/page.tsx
git commit -m "SNS 마케팅 6탭 UI — 자동포스팅/도매몰연동/수익대시보드"
```

---

## 구현 순서 요약

| Phase | Task | 내용 | 예상 |
|-------|------|------|------|
| 1 | 1~3 | 도매몰 모델 + 크롤러 + API | 백엔드 |
| 2 | 4~8 | SNS 모델 + 이슈검색 + AI글생성 + WP발행 + API | 백엔드 |
| 3 | 9~10 | 프론트 API + 6탭 UI | 프론트 |
