"""스마트스토어 소싱용 클라이언트 - 네이버 쇼핑 검색 API 기반.

주의: proxy/smartstore.py는 판매처(마켓) 등록용 클라이언트이므로,
소싱(상품 수집)용은 이 파일에서 별도로 관리한다.

네이버 쇼핑 검색 API:
  GET https://openapi.naver.com/v1/search/shop.json
  인증: X-Naver-Client-Id, X-Naver-Client-Secret 헤더
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote, urlparse, parse_qs

import httpx

from backend.core.config import settings
from backend.utils.logger import logger


class SmartStoreSourcingClient:
  """스마트스토어/네이버쇼핑 소싱용 클라이언트.

  네이버 검색 API를 활용한 상품 검색과
  스마트스토어 상품 페이지 HTML 파싱을 통한 상세 조회를 제공한다.
  """

  # 네이버 검색 API
  SEARCH_API = "https://openapi.naver.com/v1/search/shop.json"

  # 스마트스토어 / 브랜드스토어 URL 패턴
  SMARTSTORE_BASE = "https://smartstore.naver.com"
  BRAND_BASE = "https://brand.naver.com"

  HEADERS: dict[str, str] = {
    "User-Agent": (
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
  }

  def __init__(self) -> None:
    self._timeout = httpx.Timeout(20.0, connect=10.0)
    self._client_id = settings.naver_client_id
    self._client_secret = settings.naver_client_secret

  # ------------------------------------------------------------------
  # 검색
  # ------------------------------------------------------------------

  async def search_products(
    self,
    keyword: str,
    page: int = 1,
    size: int = 40,
    sort: str = "sim",
  ) -> list[dict[str, Any]]:
    """네이버 쇼핑 검색 API로 스마트스토어 상품 검색.

    Args:
      keyword: 검색 키워드
      page: 페이지 번호 (1부터)
      size: 페이지당 결과 수 (10~100)
      sort: 정렬 기준 (sim=유사도, date=날짜, asc=가격낮은순, dsc=가격높은순)

    Returns:
      표준 상품 dict 리스트
    """
    if not self._client_id or not self._client_secret:
      logger.warning("[SMARTSTORE] 네이버 API 키가 설정되지 않음 — HTML 파싱 폴백")
      return await self._search_html_fallback(keyword, page, size)

    # 네이버 검색 API 호출
    start = (page - 1) * size + 1  # API는 start 파라미터 사용 (1~1000)
    display = min(size, 100)

    logger.info(f'[SMARTSTORE] 검색 시작 (API): "{keyword}" (start={start}, display={display})')

    try:
      async with httpx.AsyncClient(timeout=self._timeout) as client:
        resp = await client.get(
          self.SEARCH_API,
          params={
            "query": keyword,
            "display": display,
            "start": start,
            "sort": sort,
          },
          headers={
            "X-Naver-Client-Id": self._client_id,
            "X-Naver-Client-Secret": self._client_secret,
          },
        )

        if resp.status_code != 200:
          logger.warning(
            f"[SMARTSTORE] 네이버 검색 API HTTP {resp.status_code}: {resp.text[:200]}"
          )
          return await self._search_html_fallback(keyword, page, size)

        data = resp.json()
        items = data.get("items", [])
        now_iso = datetime.now(tz=timezone.utc).isoformat()

        products: list[dict[str, Any]] = []
        for item in items:
          product = self._transform_api_item(item, now_iso)
          if product:
            products.append(product)

        logger.info(f'[SMARTSTORE] 검색 완료: "{keyword}" -> {len(products)}개')
        return products

    except httpx.TimeoutException:
      logger.error(f"[SMARTSTORE] 검색 타임아웃: {keyword}")
      return []
    except Exception as e:
      logger.error(f"[SMARTSTORE] 검색 실패: {keyword} — {e}")
      return []

  def _transform_api_item(
    self, item: dict[str, Any], now_iso: str
  ) -> Optional[dict[str, Any]]:
    """네이버 검색 API 결과를 표준 상품 dict로 변환.

    API 응답 필드:
      title, link, image, lprice, hprice, mallName, productId,
      productType, brand, maker, category1~4
    """
    title = re.sub(r"</?b>", "", item.get("title", ""))  # HTML 태그 제거
    link = item.get("link", "")
    product_id = item.get("productId", "")

    if not title or not product_id:
      return None

    lprice = int(item.get("lprice", "0") or "0")
    hprice = int(item.get("hprice", "0") or "0")
    image = item.get("image", "")

    # 카테고리 조합
    categories = []
    for i in range(1, 5):
      cat = item.get(f"category{i}", "")
      if cat:
        categories.append(cat)
    category_str = " > ".join(categories)

    return {
      "siteProductId": str(product_id),
      "name": title,
      "brand": item.get("brand", "") or item.get("maker", ""),
      "mallName": item.get("mallName", ""),
      "originalPrice": hprice if hprice > 0 else lprice,
      "salePrice": lprice,
      "discountRate": (
        round((1 - lprice / hprice) * 100)
        if hprice > lprice > 0
        else 0
      ),
      "thumbnailImageUrl": image,
      "isSoldOut": False,
      "productType": item.get("productType", ""),
      "category": category_str,
      "category1": item.get("category1", ""),
      "category2": item.get("category2", ""),
      "category3": item.get("category3", ""),
      "category4": item.get("category4", ""),
      "sourceSite": "SMARTSTORE",
      "sourceUrl": link,
      "collectedAt": now_iso,
    }

  async def _search_html_fallback(
    self, keyword: str, page: int = 1, size: int = 40
  ) -> list[dict[str, Any]]:
    """네이버 API 키가 없을 때 HTML 파싱 폴백.

    네이버 쇼핑 검색 페이지를 직접 요청하여 파싱한다.
    """
    search_url = (
      f"https://search.shopping.naver.com/search/all"
      f"?query={quote(keyword)}&pagingIndex={page}&pagingSize={size}"
    )
    logger.info(f'[SMARTSTORE] 검색 폴백 (HTML): "{keyword}"')

    try:
      async with httpx.AsyncClient(
        timeout=self._timeout, follow_redirects=True
      ) as client:
        resp = await client.get(search_url, headers=self.HEADERS)
        if resp.status_code != 200:
          logger.warning(f"[SMARTSTORE] HTML 폴백 HTTP {resp.status_code}")
          return []

      html = resp.text
      products: list[dict[str, Any]] = []
      now_iso = datetime.now(tz=timezone.utc).isoformat()

      # __NEXT_DATA__ JSON에서 상품 데이터 추출 시도
      next_data_match = re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
      )
      if next_data_match:
        import json
        try:
          next_data = json.loads(next_data_match.group(1))
          items = (
            next_data.get("props", {})
            .get("pageProps", {})
            .get("initialState", {})
            .get("products", {})
            .get("list", [])
          )
          for item_wrapper in items:
            item = item_wrapper.get("item", item_wrapper)
            product_id = str(item.get("id", "") or item.get("productId", ""))
            if not product_id:
              continue

            title = item.get("productTitle", "") or item.get("title", "")
            title = re.sub(r"</?b>", "", title)

            products.append({
              "siteProductId": product_id,
              "name": title,
              "brand": item.get("brand", ""),
              "mallName": item.get("mallName", ""),
              "originalPrice": item.get("price", 0),
              "salePrice": item.get("lowPrice", 0) or item.get("price", 0),
              "thumbnailImageUrl": item.get("imageUrl", ""),
              "isSoldOut": False,
              "sourceSite": "SMARTSTORE",
              "sourceUrl": item.get("crUrl", "") or item.get("productUrl", ""),
              "collectedAt": now_iso,
            })
        except (json.JSONDecodeError, KeyError) as e:
          logger.warning(f"[SMARTSTORE] __NEXT_DATA__ 파싱 실패: {e}")

      logger.info(f'[SMARTSTORE] HTML 폴백 완료: "{keyword}" -> {len(products)}개')
      return products

    except Exception as e:
      logger.error(f"[SMARTSTORE] HTML 폴백 실패: {keyword} — {e}")
      return []

  # ------------------------------------------------------------------
  # 상세 조회
  # ------------------------------------------------------------------

  async def get_product_detail(
    self, product_url_or_id: str
  ) -> dict[str, Any]:
    """스마트스토어 상품 상세 정보 조회.

    스마트스토어/브랜드스토어 상품 페이지를 HTTP로 요청 후
    __NEXT_DATA__ 또는 메타 태그에서 데이터를 추출한다.

    Args:
      product_url_or_id: 상품 URL 또는 상품 ID
        - URL: https://smartstore.naver.com/store/products/ID
        - URL: https://brand.naver.com/store/products/ID
        - ID: 숫자 문자열 (네이버쇼핑 productId)

    Returns:
      표준 상품 상세 dict
    """
    # URL인지 ID인지 판별
    if product_url_or_id.startswith("http"):
      url = product_url_or_id
    else:
      # ID만 있으면 네이버쇼핑 상품 페이지로 이동
      url = f"https://search.shopping.naver.com/product/{product_url_or_id}"

    logger.info(f"[SMARTSTORE] 상세 조회: {url}")

    try:
      async with httpx.AsyncClient(
        timeout=self._timeout, follow_redirects=True
      ) as client:
        resp = await client.get(url, headers=self.HEADERS)
        if resp.status_code != 200:
          logger.warning(f"[SMARTSTORE] 상세 페이지 HTTP {resp.status_code}")
          return {}

      html = resp.text
      now_iso = datetime.now(tz=timezone.utc).isoformat()

      # __NEXT_DATA__에서 상세 데이터 추출 시도
      detail = self._parse_next_data_detail(html, now_iso)
      if detail:
        return detail

      # 메타 태그 폴백
      return self._parse_meta_detail(html, url, now_iso)

    except httpx.TimeoutException:
      logger.error(f"[SMARTSTORE] 상세 조회 타임아웃: {product_url_or_id}")
      return {}
    except Exception as e:
      logger.error(f"[SMARTSTORE] 상세 조회 실패: {product_url_or_id} — {e}")
      return {}

  def _parse_next_data_detail(
    self, html: str, now_iso: str
  ) -> Optional[dict[str, Any]]:
    """__NEXT_DATA__ JSON에서 상품 상세 데이터 추출."""
    import json

    next_data_match = re.search(
      r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
      html,
      re.DOTALL,
    )
    if not next_data_match:
      return None

    try:
      next_data = json.loads(next_data_match.group(1))
      page_props = next_data.get("props", {}).get("pageProps", {})

      # 스마트스토어 상품 페이지 구조
      product = (
        page_props.get("product")
        or page_props.get("initialState", {}).get("product", {}).get("A", {})
        or {}
      )

      if not product:
        return None

      product_id = str(product.get("id", "") or product.get("productNo", ""))
      name = product.get("name", "") or product.get("productName", "")
      if not name:
        return None

      # 가격 정보
      sale_price = (
        product.get("salePrice", 0)
        or product.get("discountedSalePrice", 0)
        or product.get("price", 0)
      )
      original_price = product.get("originalPrice", 0) or product.get("price", 0)
      if original_price == 0:
        original_price = sale_price

      # 이미지
      images: list[str] = []
      representative_image = product.get("representativeImage", {})
      if isinstance(representative_image, dict):
        img_url = representative_image.get("url", "")
        if img_url:
          images.append(img_url)
      elif isinstance(representative_image, str) and representative_image:
        images.append(representative_image)

      # 추가 이미지
      for img in product.get("images", []):
        img_url = img.get("url", "") if isinstance(img, dict) else str(img)
        if img_url and img_url not in images:
          images.append(img_url)

      # 옵션
      options: list[dict[str, Any]] = []
      option_combinations = product.get("optionCombinations", [])
      for opt in option_combinations:
        opt_name_parts = []
        for key in ["optionName1", "optionName2", "optionName3"]:
          val = opt.get(key, "")
          if val:
            opt_name_parts.append(val)
        opt_name = " / ".join(opt_name_parts) if opt_name_parts else opt.get("name", "")

        options.append({
          "name": opt_name,
          "price": opt.get("price", 0) or opt.get("stockPrice", 0),
          "stock": opt.get("stockQuantity", 0),
          "isSoldOut": opt.get("soldout", False) or opt.get("usable", True) is False,
        })

      # 카테고리
      category_info = product.get("category", {})
      category_str = ""
      if isinstance(category_info, dict):
        cat_parts = []
        for key in ["wholeCategoryName", "categoryName"]:
          if category_info.get(key):
            category_str = category_info[key]
            break
        if not category_str:
          for key in ["category1Name", "category2Name", "category3Name", "category4Name"]:
            val = category_info.get(key, "")
            if val:
              cat_parts.append(val)
          category_str = " > ".join(cat_parts)

      # 브랜드
      brand = (
        product.get("brand", {}).get("name", "")
        if isinstance(product.get("brand"), dict)
        else product.get("brand", "")
      )

      # 상세 이미지
      detail_images: list[str] = []
      detail_content = product.get("detailContent", "")
      if detail_content:
        img_matches = re.findall(r'<img[^>]+src="([^"]+)"', detail_content)
        detail_images = [
          img for img in img_matches
          if img.startswith("http")
        ]

      thumbnail = images[0] if images else ""
      is_sold_out = product.get("saleStatus", "") == "OUTOFSTOCK" or product.get("soldout", False)

      return {
        "siteProductId": product_id,
        "name": name,
        "brand": brand,
        "originalPrice": original_price,
        "salePrice": sale_price,
        "discountRate": (
          round((1 - sale_price / original_price) * 100)
          if original_price > sale_price > 0
          else 0
        ),
        "thumbnailImageUrl": thumbnail,
        "images": images,
        "detailImages": detail_images,
        "category": category_str,
        "options": options,
        "isSoldOut": is_sold_out,
        "sourceSite": "SMARTSTORE",
        "sourceUrl": "",
        "collectedAt": now_iso,
        "updatedAt": now_iso,
      }

    except (json.JSONDecodeError, KeyError, TypeError) as e:
      logger.warning(f"[SMARTSTORE] __NEXT_DATA__ 파싱 실패: {e}")
      return None

  def _parse_meta_detail(
    self, html: str, url: str, now_iso: str
  ) -> dict[str, Any]:
    """메타 태그에서 기본 상품 정보 추출 (폴백)."""
    name = self._extract_meta(html, "og:title") or ""
    image = self._extract_meta(html, "og:image") or ""
    description = self._extract_meta(html, "og:description") or ""

    # 가격 추출
    sale_price = 0
    price_meta = self._extract_meta(html, "product:price:amount")
    if price_meta:
      sale_price = int(re.sub(r"[^\d]", "", price_meta) or "0")

    # URL에서 상품 ID 추출
    product_id = ""
    id_match = re.search(r'/products/(\d+)', url)
    if id_match:
      product_id = id_match.group(1)

    return {
      "siteProductId": product_id,
      "name": name,
      "brand": "",
      "originalPrice": sale_price,
      "salePrice": sale_price,
      "discountRate": 0,
      "thumbnailImageUrl": image,
      "images": [image] if image else [],
      "detailImages": [],
      "description": description,
      "category": "",
      "options": [],
      "isSoldOut": False,
      "sourceSite": "SMARTSTORE",
      "sourceUrl": url,
      "collectedAt": now_iso,
      "updatedAt": now_iso,
    }

  # ------------------------------------------------------------------
  # 내부 헬퍼
  # ------------------------------------------------------------------

  @staticmethod
  def _extract_meta(html: str, prop: str) -> Optional[str]:
    """og/product 메타 태그에서 content 추출."""
    pattern = rf'<meta[^>]+(?:property|name)="{re.escape(prop)}"[^>]+content="([^"]*)"'
    m = re.search(pattern, html, re.IGNORECASE)
    if m:
      return m.group(1)
    # content가 먼저 오는 경우
    pattern2 = rf'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="{re.escape(prop)}"'
    m2 = re.search(pattern2, html, re.IGNORECASE)
    return m2.group(1) if m2 else None
