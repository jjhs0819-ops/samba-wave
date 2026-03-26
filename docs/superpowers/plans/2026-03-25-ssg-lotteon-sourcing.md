# SSG/롯데ON 소싱처 추가 + 최대혜택가 체크박스 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SSG(신세계몰)와 롯데ON을 소싱처로 추가하고, 수집 시 최대혜택가 선택 체크박스를 제공한다.

**Architecture:** 무신사 패턴을 참고한 하이브리드 방식. 기본 정보(상품명, 가격, 이미지, 옵션)는 서버 HTTP 크롤링, 최대혜택가(쿠폰/적립금 포함 최저가)는 확장앱 연동. SourcingPlugin ABC를 상속한 플러그인 자동 등록 방식.

**Tech Stack:** Python 3.12, FastAPI, httpx, BeautifulSoup4, SourcingPlugin ABC

---

## 파일 구조

| 역할 | 파일 | 설명 |
|------|------|------|
| SSG 프록시 | `backend/backend/domain/samba/proxy/ssg_sourcing.py` (신규) | SSG 검색/상세 HTTP 크롤링 클라이언트 |
| 롯데ON 프록시 | `backend/backend/domain/samba/proxy/lotteon_sourcing.py` (신규) | 롯데ON 검색/상세 HTTP 크롤링 클라이언트 |
| SSG 플러그인 | `backend/backend/domain/samba/plugins/sourcing/ssg.py` (신규) | SourcingPlugin 구현 |
| 롯데ON 플러그인 | `backend/backend/domain/samba/plugins/sourcing/lotteon.py` (신규) | SourcingPlugin 구현 |
| 라우터 | `backend/backend/api/v1/routers/samba/collector.py` (수정) | SSG/LOTTEON 분기 추가, URL 자동감지 |
| 리프레셔 | `backend/backend/domain/samba/collector/refresher.py` (수정) | SSG/LOTTEON 인터벌 설정 |
| 프론트 수집기 | `frontend/src/app/samba/collector/page.tsx` (수정) | SITES에 SSG 추가, SITE_OPTIONS 확장 |
| 프론트 분석 | `frontend/src/app/samba/analytics/page.tsx` (수정) | SOURCE_SITES 동기화 |
| 프론트 배송 | `frontend/src/app/samba/shipments/page.tsx` (수정) | SOURCE_SITES 동기화 |
| 스킬 | `.claude/skills/product-parser/SKILL.md` (수정) | SSG/롯데ON 패턴 추가 |

---

### Task 1: SSG 소싱 프록시 클라이언트

**Files:**
- Create: `backend/backend/domain/samba/proxy/ssg_sourcing.py`

- [ ] **Step 1: SSG 소싱 프록시 클라이언트 생성**

```python
"""SSG(신세계몰) 소싱용 웹 스크래핑 클라이언트.

주의: proxy/ssg.py는 판매처(마켓) 등록용 클라이언트.
소싱(상품 수집)용은 이 파일에서 별도 관리한다.

SSG는 robots.txt가 엄격하므로 보수적 간격(1초+)으로 요청.
department.ssg.com 검색 API + 상품 상세 HTML 파싱.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote, urlencode

import httpx

from backend.utils.logger import logger


class SSGSourcingClient:
  """SSG 소싱용 클라이언트 (검색, 상세)."""

  SEARCH_URL = "https://department.ssg.com/search.ssg"
  ITEM_URL = "https://department.ssg.com/item/itemView.ssg"
  # SSG 내부 검색 API (JSON)
  SEARCH_API = "https://department.ssg.com/search/api/list"

  HEADERS: dict[str, str] = {
    "User-Agent": (
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://department.ssg.com/",
  }

  JSON_HEADERS: dict[str, str] = {
    "User-Agent": (
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://department.ssg.com/",
    "X-Requested-With": "XMLHttpRequest",
  }

  def __init__(self, cookie: str = "") -> None:
    self._timeout = httpx.Timeout(20.0, connect=10.0)
    self._cookie = cookie

  # ------------------------------------------------------------------
  # 검색
  # ------------------------------------------------------------------

  async def search_products(
    self,
    keyword: str,
    page: int = 1,
    size: int = 40,
    **filters: Any,
  ) -> list[dict[str, Any]]:
    """SSG 상품 검색.

    검색 페이지 HTML을 파싱하여 상품 목록을 추출한다.

    Args:
      keyword: 검색 키워드
      page: 페이지 번호 (1부터)
      size: 페이지당 결과 수

    Returns:
      표준 상품 dict 리스트
    """
    params = {
      "query": keyword,
      "page": page,
      "count": size,
      "target": "department",
    }
    headers = {**self.HEADERS}
    if self._cookie:
      headers["Cookie"] = self._cookie

    try:
      async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
        resp = await client.get(self.SEARCH_URL, params=params, headers=headers)
        resp.raise_for_status()
        html = resp.text

      return self._parse_search_html(html)

    except httpx.HTTPStatusError as e:
      if e.response.status_code in (429, 403):
        logger.warning(f"[SSG] 검색 차단: {e.response.status_code}")
        raise RateLimitError(f"SSG 요청 제한: {e.response.status_code}")
      logger.error(f"[SSG] 검색 실패: {e}")
      return []
    except Exception as e:
      logger.error(f"[SSG] 검색 에러: {e}")
      return []

  def _parse_search_html(self, html: str) -> list[dict[str, Any]]:
    """검색 결과 HTML에서 상품 목록 추출."""
    results: list[dict[str, Any]] = []

    # SSG 검색 결과는 data-info 속성에 JSON으로 상품 정보 포함
    # 또는 <script> 태그 내 상품 데이터 파싱
    item_pattern = re.compile(
      r'data-unitid="(\d+)".*?'
      r'class="[^"]*cunit_prod[^"]*"',
      re.DOTALL,
    )

    # 상품 ID 추출
    item_ids = re.findall(r'data-unitid="(\d+)"', html)

    # 상품명 추출
    names = re.findall(r'class="[^"]*cunit_info[^"]*"[^>]*>.*?<em[^>]*>(.*?)</em>', html, re.DOTALL)

    # 가격 추출
    prices = re.findall(r'class="[^"]*ssg_price[^"]*"[^>]*>([\d,]+)', html)

    # 이미지 추출
    images = re.findall(r'data-src="(https?://[^"]+\.(?:jpg|jpeg|png|webp))"', html, re.IGNORECASE)
    if not images:
      images = re.findall(r'src="(https?://sitem\.ssgcdn\.com/[^"]+)"', html)

    for i, item_id in enumerate(item_ids):
      name = names[i].strip() if i < len(names) else ""
      # HTML 태그 제거
      name = re.sub(r'<[^>]+>', '', name).strip()
      price_str = prices[i].replace(",", "") if i < len(prices) else "0"
      image = images[i] if i < len(images) else ""

      results.append({
        "siteProductId": item_id,
        "goodsNo": item_id,
        "name": name,
        "salePrice": int(price_str) if price_str.isdigit() else 0,
        "originalPrice": int(price_str) if price_str.isdigit() else 0,
        "image": image,
        "isSoldOut": False,
      })

    logger.info(f"[SSG] 검색 결과: {len(results)}건")
    return results

  # ------------------------------------------------------------------
  # 상세 조회
  # ------------------------------------------------------------------

  async def get_product_detail(
    self,
    item_id: str,
    refresh_only: bool = False,
  ) -> dict[str, Any]:
    """SSG 상품 상세 조회.

    상품 페이지 HTML을 파싱하여 상세 정보를 추출한다.

    Args:
      item_id: SSG 상품 ID (itemId)
      refresh_only: True면 고시정보 등 스킵

    Returns:
      표준 상품 dict
    """
    url = f"{self.ITEM_URL}?itemId={item_id}"
    headers = {**self.HEADERS}
    if self._cookie:
      headers["Cookie"] = self._cookie

    try:
      async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        html = resp.text

      return self._parse_detail_html(html, item_id)

    except httpx.HTTPStatusError as e:
      if e.response.status_code in (429, 403):
        raise RateLimitError(f"SSG 요청 제한: {e.response.status_code}")
      logger.error(f"[SSG] 상세 조회 실패: {item_id} — {e}")
      return {}
    except Exception as e:
      logger.error(f"[SSG] 상세 조회 에러: {item_id} — {e}")
      return {}

  def _parse_detail_html(self, html: str, item_id: str) -> dict[str, Any]:
    """상품 상세 HTML 파싱."""
    now = datetime.now(timezone.utc).isoformat()

    # 상품명
    name = ""
    name_match = re.search(r'<h2[^>]*class="[^"]*cdtl_info_tit[^"]*"[^>]*>(.*?)</h2>', html, re.DOTALL)
    if name_match:
      name = re.sub(r'<[^>]+>', '', name_match.group(1)).strip()
    if not name:
      # og:title 폴백
      og_match = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', html)
      if og_match:
        name = og_match.group(1).strip()

    # 브랜드
    brand = ""
    brand_match = re.search(r'class="[^"]*cdtl_brand_nm[^"]*"[^>]*>(.*?)<', html, re.DOTALL)
    if brand_match:
      brand = re.sub(r'<[^>]+>', '', brand_match.group(1)).strip()

    # 가격
    original_price = 0
    sale_price = 0

    # 판매가 (할인가)
    sale_match = re.search(r'class="[^"]*cdtl_new_price[^"]*"[^>]*>.*?([\d,]+)', html, re.DOTALL)
    if sale_match:
      sale_price = int(sale_match.group(1).replace(",", ""))

    # 정상가
    orig_match = re.search(r'class="[^"]*cdtl_old_price[^"]*"[^>]*>.*?([\d,]+)', html, re.DOTALL)
    if orig_match:
      original_price = int(orig_match.group(1).replace(",", ""))

    if original_price == 0:
      original_price = sale_price

    # 이미지
    images: list[str] = []
    # 대표 이미지
    og_img = re.search(r'<meta\s+property="og:image"\s+content="([^"]*)"', html)
    if og_img:
      images.append(og_img.group(1))
    # 추가 이미지 (썸네일 영역)
    thumb_imgs = re.findall(r'data-src="(https?://sitem\.ssgcdn\.com/[^"]+)"', html)
    for img in thumb_imgs:
      if img not in images and len(images) < 9:
        images.append(img)

    # 상세 이미지
    detail_images: list[str] = []
    detail_section = re.search(r'id="[^"]*cdtl_cont[^"]*"(.*?)(?:<div[^>]*class="[^"]*cdtl_|$)', html, re.DOTALL)
    if detail_section:
      detail_imgs = re.findall(r'src="(https?://[^"]+\.(?:jpg|jpeg|png|webp))"', detail_section.group(1), re.IGNORECASE)
      for img in detail_imgs:
        if "icon" not in img.lower() and "btn_" not in img.lower():
          detail_images.append(img)

    # 옵션 (data 속성 또는 script에서 추출)
    options: list[dict] = []
    option_data = re.findall(
      r'"optionName"\s*:\s*"([^"]+)".*?"optionPrice"\s*:\s*(\d+).*?"soldOutYn"\s*:\s*"([YN])"',
      html, re.DOTALL,
    )
    for opt_name, opt_price, sold_out in option_data:
      options.append({
        "name": opt_name,
        "price": sale_price + int(opt_price),
        "stock": 0 if sold_out == "Y" else 999,
        "isSoldOut": sold_out == "Y",
      })

    # 카테고리 (breadcrumb)
    cat_parts: list[str] = []
    breadcrumbs = re.findall(r'class="[^"]*location_item[^"]*"[^>]*>.*?<a[^>]*>(.*?)</a>', html, re.DOTALL)
    for bc in breadcrumbs:
      cat_name = re.sub(r'<[^>]+>', '', bc).strip()
      if cat_name and cat_name not in ("홈", "HOME"):
        cat_parts.append(cat_name)
    raw_cat = " > ".join(cat_parts) if cat_parts else ""

    # 품절 여부
    is_sold_out = "품절" in html or "soldout" in html.lower()
    sale_status = "sold_out" if is_sold_out else "in_stock"

    # 최대혜택가 (쿠폰/적립금 포함 — 확장앱 연동 시 업데이트)
    best_benefit_price = sale_price  # 기본값: 판매가

    # 쿠폰 할인 추출 시도
    coupon_match = re.search(r'data-coupon-price="(\d+)"', html)
    if coupon_match:
      coupon_price = int(coupon_match.group(1))
      if 0 < coupon_price < sale_price:
        best_benefit_price = coupon_price

    # 적립금/포인트 할인 추출 시도
    point_match = re.search(r'class="[^"]*cdtl_point[^"]*"[^>]*>.*?([\d,]+)', html, re.DOTALL)
    if point_match:
      point_val = int(point_match.group(1).replace(",", ""))
      if point_val > 0:
        best_benefit_price = max(0, best_benefit_price - point_val)

    return {
      "id": f"col_ssg_{item_id}_{int(datetime.now(timezone.utc).timestamp())}",
      "sourceSite": "SSG",
      "siteProductId": str(item_id),
      "sourceUrl": f"https://department.ssg.com/item/itemView.ssg?itemId={item_id}",
      "name": name,
      "brand": brand,
      "category": raw_cat,
      "category1": cat_parts[0] if len(cat_parts) > 0 else None,
      "category2": cat_parts[1] if len(cat_parts) > 1 else None,
      "category3": cat_parts[2] if len(cat_parts) > 2 else None,
      "category4": cat_parts[3] if len(cat_parts) > 3 else None,
      "images": images,
      "detailImages": detail_images,
      "options": options,
      "originalPrice": original_price,
      "salePrice": sale_price,
      "bestBenefitPrice": best_benefit_price,
      "saleStatus": sale_status,
      "isOutOfStock": is_sold_out,
      "freeShipping": "무료배송" in html,
      "sameDayDelivery": "당일배송" in html or "쓱배송" in html,
      "collectedAt": now,
      "updatedAt": now,
    }


class RateLimitError(Exception):
  """SSG 요청 제한 에러."""
  pass
```

- [ ] **Step 2: 커밋**

```bash
git add backend/backend/domain/samba/proxy/ssg_sourcing.py
git commit -m "SSG 소싱용 프록시 클라이언트 추가"
```

---

### Task 2: 롯데ON 소싱 프록시 클라이언트

**Files:**
- Create: `backend/backend/domain/samba/proxy/lotteon_sourcing.py`

- [ ] **Step 1: 롯데ON 소싱 프록시 클라이언트 생성**

```python
"""롯데ON 소싱용 웹 스크래핑 클라이언트.

주의: proxy/lotteon.py는 판매처(마켓) 등록용 클라이언트.
소싱(상품 수집)용은 이 파일에서 별도 관리한다.

롯데ON은 JSON-LD(schema.org) 마크업을 지원하므로 이를 우선 활용.
검색은 lotteon.com/search/ 경로 HTML 파싱.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote, urlencode

import httpx

from backend.utils.logger import logger


class LotteonSourcingClient:
  """롯데ON 소싱용 클라이언트 (검색, 상세)."""

  SEARCH_URL = "https://www.lotteon.com/search/search/search.ecn"
  ITEM_URL = "https://www.lotteon.com/p/product"

  HEADERS: dict[str, str] = {
    "User-Agent": (
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.lotteon.com/",
  }

  def __init__(self, cookie: str = "") -> None:
    self._timeout = httpx.Timeout(20.0, connect=10.0)
    self._cookie = cookie

  # ------------------------------------------------------------------
  # 검색
  # ------------------------------------------------------------------

  async def search_products(
    self,
    keyword: str,
    page: int = 1,
    size: int = 40,
    **filters: Any,
  ) -> list[dict[str, Any]]:
    """롯데ON 상품 검색.

    Args:
      keyword: 검색 키워드
      page: 페이지 번호 (1부터)
      size: 페이지당 결과 수

    Returns:
      표준 상품 dict 리스트
    """
    params = {
      "render": "search",
      "platform": "pc",
      "q": keyword,
      "page": page,
      "mallNo": "1",
    }
    headers = {**self.HEADERS}
    if self._cookie:
      headers["Cookie"] = self._cookie

    try:
      async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
        resp = await client.get(self.SEARCH_URL, params=params, headers=headers)
        resp.raise_for_status()
        html = resp.text

      return self._parse_search_html(html)

    except httpx.HTTPStatusError as e:
      if e.response.status_code in (429, 403):
        logger.warning(f"[LOTTEON] 검색 차단: {e.response.status_code}")
        raise RateLimitError(f"롯데ON 요청 제한: {e.response.status_code}")
      logger.error(f"[LOTTEON] 검색 실패: {e}")
      return []
    except Exception as e:
      logger.error(f"[LOTTEON] 검색 에러: {e}")
      return []

  def _parse_search_html(self, html: str) -> list[dict[str, Any]]:
    """검색 결과 HTML에서 상품 목록 추출."""
    results: list[dict[str, Any]] = []

    # 롯데ON 검색 결과 JSON 데이터 추출 시도
    # __NEXT_DATA__ 또는 data-product-info 속성 파싱
    json_match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if json_match:
      try:
        next_data = json.loads(json_match.group(1))
        products = (
          next_data.get("props", {})
          .get("pageProps", {})
          .get("searchResult", {})
          .get("products", [])
        )
        for prod in products:
          results.append({
            "siteProductId": prod.get("spdNo", ""),
            "goodsNo": prod.get("spdNo", ""),
            "name": prod.get("spdNm", ""),
            "salePrice": int(prod.get("slPrc", 0)),
            "originalPrice": int(prod.get("nrmPrc", prod.get("slPrc", 0))),
            "image": prod.get("imgUrl", ""),
            "isSoldOut": prod.get("soldOutYn", "N") == "Y",
            "brand": prod.get("brndNm", ""),
          })
        if results:
          logger.info(f"[LOTTEON] 검색 결과: {len(results)}건 (JSON)")
          return results
      except (json.JSONDecodeError, KeyError, TypeError):
        pass

    # HTML 폴백: 상품 카드에서 추출
    product_ids = re.findall(r'data-product-no="([^"]+)"', html)
    names = re.findall(r'class="[^"]*srchProductUnitTitle[^"]*"[^>]*>(.*?)<', html, re.DOTALL)
    prices = re.findall(r'class="[^"]*srchProductUnitPrice[^"]*"[^>]*>.*?([\d,]+)', html, re.DOTALL)
    images = re.findall(r'data-src="(https?://contents\.lotteon\.com/[^"]+)"', html)
    if not images:
      images = re.findall(r'src="(https?://contents\.lotteon\.com/[^"]+)"', html)

    for i, pid in enumerate(product_ids):
      name = re.sub(r'<[^>]+>', '', names[i]).strip() if i < len(names) else ""
      price_str = prices[i].replace(",", "") if i < len(prices) else "0"
      image = images[i] if i < len(images) else ""

      results.append({
        "siteProductId": pid,
        "goodsNo": pid,
        "name": name,
        "salePrice": int(price_str) if price_str.isdigit() else 0,
        "originalPrice": int(price_str) if price_str.isdigit() else 0,
        "image": image,
        "isSoldOut": False,
      })

    logger.info(f"[LOTTEON] 검색 결과: {len(results)}건")
    return results

  # ------------------------------------------------------------------
  # 상세 조회
  # ------------------------------------------------------------------

  async def get_product_detail(
    self,
    product_no: str,
    refresh_only: bool = False,
  ) -> dict[str, Any]:
    """롯데ON 상품 상세 조회.

    JSON-LD(schema.org)를 우선 파싱하고, HTML로 보충.

    Args:
      product_no: 롯데ON 상품 번호 (LO 접두사 포함 가능)
      refresh_only: True면 고시정보 등 스킵

    Returns:
      표준 상품 dict
    """
    # LO 접두사 없으면 추가
    if not product_no.startswith("LO"):
      product_no = f"LO{product_no}"

    url = f"{self.ITEM_URL}/{product_no}"
    headers = {**self.HEADERS}
    if self._cookie:
      headers["Cookie"] = self._cookie

    try:
      async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        html = resp.text

      return self._parse_detail_html(html, product_no)

    except httpx.HTTPStatusError as e:
      if e.response.status_code in (429, 403):
        raise RateLimitError(f"롯데ON 요청 제한: {e.response.status_code}")
      logger.error(f"[LOTTEON] 상세 조회 실패: {product_no} — {e}")
      return {}
    except Exception as e:
      logger.error(f"[LOTTEON] 상세 조회 에러: {product_no} — {e}")
      return {}

  def _parse_detail_html(self, html: str, product_no: str) -> dict[str, Any]:
    """상품 상세 HTML 파싱 (JSON-LD 우선)."""
    now = datetime.now(timezone.utc).isoformat()

    name = ""
    brand = ""
    sale_price = 0
    original_price = 0
    images: list[str] = []
    detail_images: list[str] = []
    options: list[dict] = []

    # 1단계: JSON-LD 파싱
    json_ld_match = re.search(
      r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
      html, re.DOTALL,
    )
    if json_ld_match:
      try:
        ld = json.loads(json_ld_match.group(1))
        if ld.get("@type") == "Product":
          name = ld.get("name", "")
          if ld.get("image"):
            img = ld["image"]
            if isinstance(img, str):
              images.append(img)
            elif isinstance(img, list):
              images.extend(img[:9])
          offers = ld.get("offers", {})
          if isinstance(offers, dict):
            sale_price = int(offers.get("price", 0))
          elif isinstance(offers, list) and offers:
            sale_price = int(offers[0].get("price", 0))
      except (json.JSONDecodeError, ValueError):
        pass

    # 2단계: HTML 보충
    if not name:
      og_title = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', html)
      if og_title:
        name = og_title.group(1).strip()

    if not brand:
      brand_match = re.search(r'class="[^"]*brand[^"]*"[^>]*>.*?<a[^>]*>(.*?)</a>', html, re.DOTALL)
      if brand_match:
        brand = re.sub(r'<[^>]+>', '', brand_match.group(1)).strip()

    # 정상가
    orig_match = re.search(r'class="[^"]*original[_-]?price[^"]*"[^>]*>.*?([\d,]+)', html, re.DOTALL)
    if orig_match:
      original_price = int(orig_match.group(1).replace(",", ""))
    if original_price == 0:
      original_price = sale_price

    # 추가 이미지
    if not images:
      og_img = re.search(r'<meta\s+property="og:image"\s+content="([^"]*)"', html)
      if og_img:
        images.append(og_img.group(1))

    # 상품 이미지 슬라이더
    slider_imgs = re.findall(
      r'src="(https?://contents\.lotteon\.com/itemimage/[^"]+)"',
      html,
    )
    for img in slider_imgs:
      if img not in images and len(images) < 9:
        images.append(img)

    # 상세 이미지
    detail_section = re.search(r'id="[^"]*productDetail[^"]*"(.*?)(?:<div[^>]*id="[^"]*productReview|$)', html, re.DOTALL)
    if detail_section:
      det_imgs = re.findall(r'src="(https?://[^"]+\.(?:jpg|jpeg|png|webp))"', detail_section.group(1), re.IGNORECASE)
      for img in det_imgs:
        if "icon" not in img.lower() and "btn_" not in img.lower():
          detail_images.append(img)

    # 옵션 (__NEXT_DATA__ 또는 data 속성에서 추출)
    next_data_match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if next_data_match:
      try:
        nd = json.loads(next_data_match.group(1))
        items = (
          nd.get("props", {})
          .get("pageProps", {})
          .get("product", {})
          .get("itmLst", [])
        )
        for item in items:
          opt_names = []
          for opt in item.get("itmOptLst", []):
            opt_names.append(f"{opt.get('optNm', '')}: {opt.get('optVal', '')}")
          opt_name = " / ".join(opt_names) if opt_names else item.get("eitmNo", "")
          options.append({
            "name": opt_name,
            "price": int(item.get("slPrc", sale_price)),
            "stock": int(item.get("stkQty", 0)),
            "isSoldOut": int(item.get("stkQty", 0)) <= 0,
          })
      except (json.JSONDecodeError, KeyError, TypeError):
        pass

    # 카테고리 (breadcrumb)
    cat_parts: list[str] = []
    breadcrumbs = re.findall(r'class="[^"]*breadcrumb[^"]*".*?<a[^>]*>(.*?)</a>', html, re.DOTALL)
    for bc in breadcrumbs:
      cat_name = re.sub(r'<[^>]+>', '', bc).strip()
      if cat_name and cat_name not in ("홈", "HOME", "전체"):
        cat_parts.append(cat_name)
    raw_cat = " > ".join(cat_parts) if cat_parts else ""

    # 품절 여부
    is_sold_out = "품절" in html or "soldout" in html.lower()
    sale_status = "sold_out" if is_sold_out else "in_stock"

    # 최대혜택가 (쿠폰/적립금 포함 — 확장앱 연동 시 업데이트)
    best_benefit_price = sale_price

    # 쿠폰 할인 추출 시도
    coupon_match = re.search(r'coupon.*?price.*?([\d,]+)', html, re.IGNORECASE | re.DOTALL)
    if coupon_match:
      cp = int(coupon_match.group(1).replace(",", ""))
      if 0 < cp < sale_price:
        best_benefit_price = cp

    return {
      "id": f"col_lotteon_{product_no}_{int(datetime.now(timezone.utc).timestamp())}",
      "sourceSite": "LOTTEON",
      "siteProductId": str(product_no),
      "sourceUrl": f"https://www.lotteon.com/p/product/{product_no}",
      "name": name,
      "brand": brand,
      "category": raw_cat,
      "category1": cat_parts[0] if len(cat_parts) > 0 else None,
      "category2": cat_parts[1] if len(cat_parts) > 1 else None,
      "category3": cat_parts[2] if len(cat_parts) > 2 else None,
      "category4": cat_parts[3] if len(cat_parts) > 3 else None,
      "images": images,
      "detailImages": detail_images,
      "options": options,
      "originalPrice": original_price,
      "salePrice": sale_price,
      "bestBenefitPrice": best_benefit_price,
      "saleStatus": sale_status,
      "isOutOfStock": is_sold_out,
      "freeShipping": "무료배송" in html,
      "sameDayDelivery": "바로배송" in html or "당일배송" in html,
      "collectedAt": now,
      "updatedAt": now,
    }


class RateLimitError(Exception):
  """롯데ON 요청 제한 에러."""
  pass
```

- [ ] **Step 2: 커밋**

```bash
git add backend/backend/domain/samba/proxy/lotteon_sourcing.py
git commit -m "롯데ON 소싱용 프록시 클라이언트 추가"
```

---

### Task 3: SSG/롯데ON 소싱 플러그인

**Files:**
- Create: `backend/backend/domain/samba/plugins/sourcing/ssg.py`
- Create: `backend/backend/domain/samba/plugins/sourcing/lotteon.py`

- [ ] **Step 1: SSG 소싱 플러그인 생성**

```python
"""SSG(신세계몰) 소싱처 플러그인."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
  from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class SSGPlugin(SourcingPlugin):
  """SSG 소싱처 플러그인.

  SSG는 robots.txt가 엄격하므로 보수적 설정.
  concurrency=1: 동시 1개만
  request_interval=1.0: 요청 간 1초 딜레이
  """

  site_name = "SSG"
  concurrency = 1
  request_interval = 1.0

  async def search(self, keyword: str, **filters) -> list[dict]:
    """SSG 키워드 검색."""
    from backend.domain.samba.proxy.ssg_sourcing import SSGSourcingClient

    cookie = filters.pop("cookie", "")
    client = SSGSourcingClient(cookie=cookie)
    return await self.safe_call(
      client.search_products(keyword, **filters)
    )

  async def get_detail(self, site_product_id: str) -> dict:
    """SSG 상품 상세 조회."""
    from backend.domain.samba.proxy.ssg_sourcing import SSGSourcingClient

    client = SSGSourcingClient()
    return await self.safe_call(
      client.get_product_detail(site_product_id)
    )

  async def refresh(self, product) -> "RefreshResult":
    """가격/재고 갱신."""
    from backend.domain.samba.collector.refresher import RefreshResult
    from backend.domain.samba.proxy.ssg_sourcing import SSGSourcingClient

    product_id = getattr(product, "id", "")
    site_product_id = getattr(product, "site_product_id", "") or getattr(
      product, "siteProductId", ""
    )

    if not site_product_id:
      return RefreshResult(product_id=product_id, error="SSG 상품 ID 없음")

    try:
      client = SSGSourcingClient()
      detail = await self.safe_call(
        client.get_product_detail(site_product_id, refresh_only=True)
      )

      if not detail:
        return RefreshResult(
          product_id=product_id,
          error=f"SSG 상세 조회 실패: {site_product_id}",
        )

      new_sale_price = detail.get("salePrice", 0)
      new_original_price = detail.get("originalPrice", 0)
      new_cost = detail.get("bestBenefitPrice")
      is_sold_out = detail.get("isOutOfStock", False)

      new_options = None
      raw_options = detail.get("options", [])
      if raw_options:
        new_options = raw_options

      return RefreshResult(
        product_id=product_id,
        new_sale_price=float(new_sale_price) if new_sale_price else None,
        new_original_price=float(new_original_price) if new_original_price else None,
        new_cost=float(new_cost) if new_cost and new_cost > 0 else None,
        new_sale_status="sold_out" if is_sold_out else "in_stock",
        new_options=new_options,
        new_images=detail.get("images"),
        new_detail_images=detail.get("detailImages"),
        changed=True,
      )

    except Exception as e:
      logger.error(f"[SSG] 갱신 실패: {site_product_id} — {e}")
      return RefreshResult(product_id=product_id, error=f"SSG 갱신 실패: {e}")
```

- [ ] **Step 2: 롯데ON 소싱 플러그인 생성**

```python
"""롯데ON 소싱처 플러그인."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
  from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class LotteonPlugin(SourcingPlugin):
  """롯데ON 소싱처 플러그인.

  롯데ON은 JSON-LD 지원으로 파싱이 비교적 안정적.
  concurrency=2: 동시 2개
  request_interval=0.5: 요청 간 500ms 딜레이
  """

  site_name = "LOTTEON"
  concurrency = 2
  request_interval = 0.5

  async def search(self, keyword: str, **filters) -> list[dict]:
    """롯데ON 키워드 검색."""
    from backend.domain.samba.proxy.lotteon_sourcing import LotteonSourcingClient

    cookie = filters.pop("cookie", "")
    client = LotteonSourcingClient(cookie=cookie)
    return await self.safe_call(
      client.search_products(keyword, **filters)
    )

  async def get_detail(self, site_product_id: str) -> dict:
    """롯데ON 상품 상세 조회."""
    from backend.domain.samba.proxy.lotteon_sourcing import LotteonSourcingClient

    client = LotteonSourcingClient()
    return await self.safe_call(
      client.get_product_detail(site_product_id)
    )

  async def refresh(self, product) -> "RefreshResult":
    """가격/재고 갱신."""
    from backend.domain.samba.collector.refresher import RefreshResult
    from backend.domain.samba.proxy.lotteon_sourcing import LotteonSourcingClient

    product_id = getattr(product, "id", "")
    site_product_id = getattr(product, "site_product_id", "") or getattr(
      product, "siteProductId", ""
    )

    if not site_product_id:
      return RefreshResult(product_id=product_id, error="롯데ON 상품 ID 없음")

    try:
      client = LotteonSourcingClient()
      detail = await self.safe_call(
        client.get_product_detail(site_product_id, refresh_only=True)
      )

      if not detail:
        return RefreshResult(
          product_id=product_id,
          error=f"롯데ON 상세 조회 실패: {site_product_id}",
        )

      new_sale_price = detail.get("salePrice", 0)
      new_original_price = detail.get("originalPrice", 0)
      new_cost = detail.get("bestBenefitPrice")
      is_sold_out = detail.get("isOutOfStock", False)

      new_options = None
      raw_options = detail.get("options", [])
      if raw_options:
        new_options = raw_options

      return RefreshResult(
        product_id=product_id,
        new_sale_price=float(new_sale_price) if new_sale_price else None,
        new_original_price=float(new_original_price) if new_original_price else None,
        new_cost=float(new_cost) if new_cost and new_cost > 0 else None,
        new_sale_status="sold_out" if is_sold_out else "in_stock",
        new_options=new_options,
        new_images=detail.get("images"),
        new_detail_images=detail.get("detailImages"),
        changed=True,
      )

    except Exception as e:
      logger.error(f"[LOTTEON] 갱신 실패: {site_product_id} — {e}")
      return RefreshResult(product_id=product_id, error=f"롯데ON 갱신 실패: {e}")
```

- [ ] **Step 3: 커밋**

```bash
git add backend/backend/domain/samba/plugins/sourcing/ssg.py backend/backend/domain/samba/plugins/sourcing/lotteon.py
git commit -m "SSG/롯데ON 소싱 플러그인 추가"
```

---

### Task 4: collector 라우터에 SSG/롯데ON 분기 추가

**Files:**
- Modify: `backend/backend/api/v1/routers/samba/collector.py`
  - URL 자동감지에 SSG/LOTTEON 추가 (~line 924-930)
  - collect-by-url 함수에 SSG/LOTTEON 분기 추가 (~line 1230 이후)

- [ ] **Step 1: URL 자동감지에 SSG/LOTTEON 추가**

`collector.py` 923-930줄의 사이트 자동 감지 블록에 추가:

```python
# 기존
if "musinsa.com" in url:
    site = "MUSINSA"
elif "kream.co.kr" in url:
    site = "KREAM"
# 추가
elif "ssg.com" in url:
    site = "SSG"
elif "lotteon.com" in url:
    site = "LOTTEON"
else:
    raise HTTPException(400, "지원하지 않는 URL입니다. source_site를 지정해주세요.")
```

- [ ] **Step 2: SSG collect-by-url 분기 추가**

KREAM 분기 이후(~line 1400+)에 SSG 분기 추가. 무신사 패턴을 복제하되:
- `SSGSourcingClient` 사용
- URL에서 itemId 추출 패턴: `itemId=(\d+)` 또는 `/product/(\d+)`
- 검색 URL 판별: `query=` 또는 `/search` 포함
- `maxDiscount` 옵션 파싱
- `use_max_discount` 체크 시 `bestBenefitPrice`를 cost로, 미체크 시 `salePrice`를 cost로

```python
elif site == "SSG":
    import re
    from urllib.parse import urlparse, parse_qs
    from backend.domain.samba.proxy.ssg_sourcing import SSGSourcingClient

    parsed = urlparse(url)
    is_search_url = "/search" in parsed.path or "query" in parsed.query

    if is_search_url:
        qs = parse_qs(parsed.query)
        keyword = qs.get("query", [""])[0]
        if not keyword:
            raise HTTPException(400, "검색 URL에서 키워드를 찾을 수 없습니다")

        use_max_discount = qs.get("maxDiscount", [""])[0] == "1"

        search_filter = await svc.create_filter({
            "source_site": "SSG",
            "name": keyword,
            "keyword": url,
            "requested_count": 100,
        })
        filter_id = search_filter.id

        client = SSGSourcingClient()
        # ... 무신사와 동일한 검색→상세→배치저장 패턴
    else:
        # 단일 상품 URL
        match = re.search(r'itemId=(\d+)', url)
        if not match:
            raise HTTPException(400, "SSG 상품 URL에서 상품번호를 찾을 수 없습니다")
        item_id = match.group(1)
        # ... 무신사 단일 상품 패턴 복제
```

- [ ] **Step 3: LOTTEON collect-by-url 분기 추가**

SSG와 동일 패턴, `LotteonSourcingClient` 사용:
- URL에서 상품번호 추출: `/product/(LO\d+)` 또는 `/product/(\d+)`
- 검색 URL 판별: `/search/` 또는 `q=` 포함

- [ ] **Step 4: 커밋**

```bash
git add backend/backend/api/v1/routers/samba/collector.py
git commit -m "collector 라우터에 SSG/롯데ON 수집 분기 추가"
```

---

### Task 5: refresher에 SSG/롯데ON 인터벌 설정

**Files:**
- Modify: `backend/backend/domain/samba/collector/refresher.py` (~line 20-36)

- [ ] **Step 1: 인터벌 설정 추가**

```python
# 기존 SITE_CONCURRENCY에 추가
SITE_CONCURRENCY: dict[str, int] = {
    "MUSINSA": 1,
    "SSG": 1,
    "LOTTEON": 2,
}
# 기존 SITE_BASE_INTERVAL에 추가
SITE_BASE_INTERVAL: dict[str, float] = {
    "MUSINSA": 0.0,
    "SSG": 1.0,
    "LOTTEON": 0.5,
}
# 기존 SITE_MIN_INTERVAL에 추가
SITE_MIN_INTERVAL: dict[str, float] = {
    "MUSINSA": 0.0,
    "SSG": 0.5,
    "LOTTEON": 0.3,
}
# 기존 SITE_INTERVAL_STEP에 추가
SITE_INTERVAL_STEP: dict[str, float] = {
    "MUSINSA": 0.2,
    "SSG": 0.5,
    "LOTTEON": 0.3,
}
```

- [ ] **Step 2: 커밋**

```bash
git add backend/backend/domain/samba/collector/refresher.py
git commit -m "refresher에 SSG/롯데ON 인터벌 설정 추가"
```

---

### Task 6: 프론트엔드 UI 수정

**Files:**
- Modify: `frontend/src/app/samba/collector/page.tsx` (~line 19-58)
- Modify: `frontend/src/app/samba/analytics/page.tsx` (~line 22)
- Modify: `frontend/src/app/samba/shipments/page.tsx` (~line 2)

- [ ] **Step 1: collector/page.tsx — SITES 배열에 SSG 추가**

LOTTEON은 이미 존재. SSG를 LOTTEON 앞에 추가:

```typescript
const SITES = [
  { id: 'MUSINSA', label: '무신사' },
  { id: 'KREAM', label: 'KREAM' },
  { id: 'DANAWA', label: '다나와' },
  { id: 'FashionPlus', label: '패션플러스' },
  { id: 'Nike', label: 'Nike' },
  { id: 'Adidas', label: 'Adidas' },
  { id: 'ABCmart', label: 'ABC마트' },
  { id: 'GrandStage', label: '그랜드스테이지' },
  { id: 'OKmall', label: 'OKmall' },
  { id: 'SSG', label: '신세계몰' },        // 신규
  { id: 'LOTTEON', label: '롯데ON' },
  { id: 'GSShop', label: 'GSShop' },
  { id: 'ElandMall', label: '이랜드몰' },
  { id: 'SSF', label: 'SSF샵' },
]
```

- [ ] **Step 2: SITE_COLORS에 SSG 색상 추가**

```typescript
const SITE_COLORS: Record<string, string> = {
  // 기존...
  SSG: '#FF5A2E',    // SSG 브랜드 오렌지
  // 기존 LOTTEON: '#E10044' 유지
}
```

- [ ] **Step 3: SITE_OPTIONS에 SSG/LOTTEON 최대혜택가 추가**

```typescript
const SITE_OPTIONS: Record<string, { id: string; label: string }[]> = {
  MUSINSA: [
    { id: 'excludePreorder', label: '예약배송 수집제외' },
    { id: 'excludeBoutique', label: '부티끄 수집제외' },
    { id: 'maxDiscount', label: '최대혜택가' },
  ],
  KREAM: [],
  SSG: [
    { id: 'maxDiscount', label: '최대혜택가' },
  ],
  LOTTEON: [
    { id: 'maxDiscount', label: '최대혜택가' },
  ],
}
```

- [ ] **Step 4: analytics, shipments 페이지 SOURCE_SITES 동기화**

`analytics/page.tsx`, `shipments/page.tsx`의 `SOURCE_SITES` 배열에 `'SSG'` 추가.

- [ ] **Step 5: 커밋**

```bash
git add frontend/src/app/samba/collector/page.tsx frontend/src/app/samba/analytics/page.tsx frontend/src/app/samba/shipments/page.tsx
git commit -m "프론트 UI에 SSG/롯데ON 소싱처 + 최대혜택가 체크박스 추가"
```

---

### Task 7: maxDiscount 옵션 실제 적용 (cost 계산 분기)

**Files:**
- Modify: `backend/backend/api/v1/routers/samba/collector.py`

현재 `use_max_discount` 변수는 파싱만 되고 미사용 상태. 모든 소싱처에서 실제 적용:

- [ ] **Step 1: cost 계산에 maxDiscount 분기 추가**

무신사/SSG/LOTTEON 공통:

```python
# 기존 (무신사, ~line 1079-1080)
_raw_cost = detail.get("bestBenefitPrice")
new_cost = _raw_cost if (_raw_cost is not None and _raw_cost > 0) else (detail.get("salePrice") or 0)

# 변경: maxDiscount 체크 시에만 bestBenefitPrice 사용
if use_max_discount:
    _raw_cost = detail.get("bestBenefitPrice")
    new_cost = _raw_cost if (_raw_cost is not None and _raw_cost > 0) else (detail.get("salePrice") or 0)
else:
    new_cost = detail.get("salePrice") or 0
```

- [ ] **Step 2: collect-by-filter 엔드포인트에도 동일 적용**

`collect_by_filter` 함수 내 `_use_max_discount` 변수도 실제 cost 계산에 반영.

- [ ] **Step 3: 커밋**

```bash
git add backend/backend/api/v1/routers/samba/collector.py
git commit -m "maxDiscount 체크박스 옵션 실제 cost 계산에 반영"
```

---

### Task 8: product-parser 스킬 업데이트

**Files:**
- Modify: `.claude/skills/product-parser/SKILL.md`

- [ ] **Step 1: SSG/롯데ON 소싱처 패턴 추가**

스킬 파일의 "소싱처별 수집 패턴" 섹션에 추가:

```markdown
### SSG (신세계몰)
- **프록시**: `proxy/ssg_sourcing.py` — SSGSourcingClient
- **URL 패턴**: `department.ssg.com/item/itemView.ssg?itemId={13자리}`
- **검색**: `department.ssg.com/search.ssg?query={keyword}`
- **가격**: originalPrice(정상가), salePrice(판매가), bestBenefitPrice(최대혜택가)
- **최대혜택가**: 쿠폰+적립금 포함 최저가. 확장앱 연동 시 정밀 계산.
- **이미지 CDN**: `sitem.ssgcdn.com`
- **주의**: robots.txt 엄격, concurrency=1, interval=1.0초

### 롯데ON (LOTTEON)
- **프록시**: `proxy/lotteon_sourcing.py` — LotteonSourcingClient
- **URL 패턴**: `lotteon.com/p/product/{LO+10자리}`
- **검색**: `lotteon.com/search/search/search.ecn?q={keyword}`
- **가격**: originalPrice, salePrice, bestBenefitPrice
- **최대혜택가**: 쿠폰+L.POINT 포함 최저가. 확장앱 연동 시 정밀 계산.
- **이미지 CDN**: `contents.lotteon.com`
- **JSON-LD**: schema.org Product 마크업 우선 파싱
```

- [ ] **Step 2: 커밋**

```bash
git add .claude/skills/product-parser/SKILL.md
git commit -m "product-parser 스킬에 SSG/롯데ON 패턴 추가"
```
