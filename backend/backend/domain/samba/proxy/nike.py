"""Nike 소싱 클라이언트 - 상품 검색/상세 조회.

사이트: https://www.nike.com/kr
수집 방식:
  - 검색: __NEXT_DATA__ → props.pageProps.initialState.Wall.productGroupings
  - 상세: PDP 직접 fetch → props.pageProps.selectedProduct + contentImages
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from backend.utils.logger import logger

HEADERS = {
  "User-Agent": (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
  ),
  "Accept": "text/html,application/xhtml+xml",
  "Accept-Language": "ko-KR,ko;q=0.9",
}

# productType → 한국어 카테고리 매핑
CAT_MAP = {
  "FOOTWEAR": "신발",
  "APPAREL": "의류",
  "ACCESSORIES": "액세서리",
  "EQUIPMENT": "장비",
}


class NikeClient:
  """Nike KR 소싱 클라이언트."""

  SEARCH_URL = "https://www.nike.com/kr/w"
  # PDP: styleColor만으로 접근 시 올바른 URL로 리다이렉트됨
  PDP_URL = "https://www.nike.com/kr/t/-/-/{style_color}"

  async def search(self, keyword: str, page: int = 1) -> dict[str, Any]:
    """키워드 검색 — __NEXT_DATA__.Wall.productGroupings 파싱."""
    params = {"q": keyword}
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
      resp = await client.get(self.SEARCH_URL, params=params, headers=HEADERS)
      resp.raise_for_status()
      products = self._parse_search_data(resp.text)
      logger.info(f"[Nike] 검색 '{keyword}' → {len(products)}건")
      return {"products": products, "total": len(products)}

  async def get_detail(self, style_color: str) -> dict[str, Any]:
    """상품 상세 조회 — 검색으로 PDP URL 확인 후 PDP 직접 fetch.

    Nike PDP URL은 슬러그 기반이라 styleColor만으로 바로 접근 불가.
    1단계: 검색으로 pdpUrl.url 추출
    2단계: PDP 페이지 fetch → selectedProduct 파싱
    """
    # 1단계: 검색으로 PDP URL + 기본 정보(이름) 확인
    search_result = await self.search(style_color)
    products = search_result.get("products", [])
    base_info: dict[str, Any] = {}
    pdp_url = None
    for p in products:
      if p.get("site_product_id") == style_color:
        pdp_url = p.get("url")
        base_info = p
        break
    if not pdp_url and products:
      pdp_url = products[0].get("url")
      base_info = products[0]

    if not pdp_url:
      return {"error": f"상품 {style_color}의 PDP URL을 찾을 수 없습니다."}

    # 2단계: PDP 직접 fetch → 상세 정보 (이미지, 색상, 제조국)
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
      resp = await client.get(pdp_url, headers=HEADERS)
      resp.raise_for_status()
      detail = self._parse_pdp_data(resp.text, style_color)
      if not detail:
        return {"error": f"상품 {style_color}를 파싱할 수 없습니다."}

    # 3단계: 검색 기본 정보 + PDP 상세 정보 병합
    # 이름은 검색 결과가 정확 (PDP __NEXT_DATA__에 title 없음)
    result = {**detail}
    if base_info.get("name"):
      result["name"] = base_info["name"]
    if base_info.get("sale_price") and not result.get("sale_price"):
      result["sale_price"] = base_info["sale_price"]
    if base_info.get("original_price") and not result.get("original_price"):
      result["original_price"] = base_info["original_price"]

    logger.info(f"[Nike] 상세 '{style_color}' → 이미지 {len(result.get('images', []))}장")
    return result

  @staticmethod
  def _parse_search_data(html: str) -> list[dict[str, Any]]:
    """검색 페이지 __NEXT_DATA__ → 상품 목록 추출."""
    nd_match = re.search(
      r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    if not nd_match:
      return []

    try:
      nd = json.loads(nd_match.group(1))
    except json.JSONDecodeError:
      return []

    wall = (
      nd.get("props", {})
      .get("pageProps", {})
      .get("initialState", {})
      .get("Wall", {})
    )
    groupings = wall.get("productGroupings", [])

    products = []
    for group in groupings:
      for prod in group.get("products", []):
        copy = prod.get("copy") or {}
        prices = prod.get("prices") or {}
        images = prod.get("colorwayImages") or {}
        display_colors = prod.get("displayColors") or {}
        pdp_url = prod.get("pdpUrl") or {}

        title = copy.get("title", "")
        subtitle = copy.get("subTitle", "")
        name = f"{title} {subtitle}".strip() if subtitle else title

        current_price = prices.get("currentPrice", 0)
        initial_price = prices.get("initialPrice", 0)
        img_url = images.get("portraitURL", "") or images.get("squarishURL", "")
        product_code = prod.get("productCode", "")
        product_type = prod.get("productType", "")
        category1 = CAT_MAP.get(product_type, product_type)
        color = display_colors.get("colorDescription", "")
        url = pdp_url.get("url", "") if isinstance(pdp_url, dict) else ""

        products.append({
          "site_product_id": product_code,
          "name": name or f"Nike {product_code}",
          "original_price": initial_price,
          "sale_price": current_price or initial_price,
          "images": [img_url] if img_url else [],
          "brand": "Nike",
          "source_site": "Nike",
          "category": f"Nike > {category1}" if category1 else "Nike",
          "category1": "Nike",
          "category2": category1,
          "category3": "",
          "color": color,
          "url": url,
          "options": [],
          "detail_html": "",
        })

    return products

  @staticmethod
  def _parse_pdp_data(html: str, style_color: str) -> dict[str, Any] | None:
    """PDP 페이지 __NEXT_DATA__ → 상세 정보 추출.

    props.pageProps.selectedProduct 에서:
    - title, subtitle (h1/h2 텍스트로 보완)
    - prices
    - contentImages (최대 8장)
    - colorDescription
    - manufacturingCountriesOfOrigin

    HTML에서:
    - 사이즈 라디오 버튼 label → options
    """
    nd_match = re.search(
      r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    if not nd_match:
      return None

    try:
      nd = json.loads(nd_match.group(1))
    except json.JSONDecodeError:
      return None

    page_props = nd.get("props", {}).get("pageProps", {})
    sp = page_props.get("selectedProduct") or {}

    # 제목: selectedProduct에 title 없으면 productGroups에서 추출
    title = sp.get("title", "")
    subtitle = sp.get("subtitle", "")

    if not title:
      # productGroups[0].products[styleColor] 에서 확인
      product_groups = page_props.get("productGroups") or []
      if product_groups:
        products_map = product_groups[0].get("products") or {}
        prod_data = products_map.get(style_color) or {}
        title = prod_data.get("title", "") or sp.get("groupKey", "")

    # 제목이 없으면 HTML h1 태그에서 파싱
    if not title:
      h1_match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
      if h1_match:
        title = re.sub(r'<[^>]+>', '', h1_match.group(1)).strip()

    name = f"{title} {subtitle}".strip() if subtitle else title

    # 가격
    prices = sp.get("prices") or {}
    current_price = prices.get("currentPrice", 0)
    initial_price = prices.get("initialPrice", 0)

    # 이미지: contentImages 배열에서 squarish URL 추출
    content_images = sp.get("contentImages") or []
    images = []
    for ci in content_images:
      props = ci.get("properties") or {}
      # squarish 우선, portrait 차선
      url = (
        (props.get("squarish") or {}).get("url")
        or (props.get("portrait") or {}).get("url")
      )
      if url and url not in images:
        images.append(url)

    # 추가: colorwayImages 컬렉션에서도 이미지 수집
    colorway_images = page_props.get("colorwayImages") or []
    for cw in colorway_images:
      for key in ("squarishImg", "portraitImg"):
        url = cw.get(key)
        if url and url not in images:
          images.append(url)

    # 색상/제조국
    color = sp.get("colorDescription", "")
    origin_list = sp.get("manufacturingCountriesOfOrigin") or []
    origin = ", ".join(origin_list) if origin_list else ""

    # 카테고리
    taxonomy = sp.get("taxonomyLabels") or {}
    gender = (sp.get("genders") or [""])[0]
    gender_map = {"WOMEN": "여성", "MEN": "남성", "UNISEX": "공용", "KIDS": "키즈"}
    gender_kr = gender_map.get(gender, gender)

    # 사이즈 옵션: HTML label 태그에서 파싱 (SSR에 없음)
    # <label ...>220</label> 형식 → 숫자만 있는 라벨을 사이즈로 인식
    size_labels = re.findall(r'<label[^>]*>\s*(\d{3})\s*</label>', html)
    options = [
      {"size": s, "stock": 1}
      for s in dict.fromkeys(size_labels)  # 중복 제거
    ]

    # 상품 설명 HTML (moreInfo 활용, 없으면 공란)
    detail_html = ""

    product_type = sp.get("productType", "")
    category1 = CAT_MAP.get(product_type, product_type)

    return {
      "site_product_id": style_color,
      "name": name or f"Nike {style_color}",
      "original_price": initial_price,
      "sale_price": current_price or initial_price,
      "images": images,
      "brand": "Nike",
      "source_site": "Nike",
      "category": f"Nike > {gender_kr} > {category1}".strip(" > ") if gender_kr or category1 else "Nike",
      "category1": "Nike",
      "category2": gender_kr,
      "category3": category1,
      "color": color,
      "origin": origin,
      "options": options,
      "detail_html": detail_html,
    }
