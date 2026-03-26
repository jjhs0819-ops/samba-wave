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
from urllib.parse import quote

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

  CHANNEL_ID = "d9a5bc42-4b9c-4976-858a-f159cf99c647"
  PAGE_API_URL = (
    "https://api.nike.com/discover/product_wall/v1/marketplace/KR/language/ko"
    "/consumerChannelId/d9a5bc42-4b9c-4976-858a-f159cf99c647"
  )
  PAGE_SIZE = 24

  async def search(self, keyword: str, page: int = 1, max_count: int = 500) -> dict[str, Any]:
    """키워드 검색 — 1페이지: HTML __NEXT_DATA__ 파싱, 2페이지~: Nike API 호출.

    nike-api-caller-id 헤더값이 핵심:
      com.nike.commerce.nikedotcom.web  (실제 사이트가 사용하는 값)
    """
    import asyncio
    products: list[dict[str, Any]] = []
    total_resources = 0
    last_error = ""

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
      # 1단계: 첫 페이지 HTML 파싱
      params: dict[str, Any] = {"q": keyword}
      resp = await client.get(self.SEARCH_URL, params=params, headers=HEADERS)
      resp.raise_for_status()
      products, total_resources = self._parse_search_data_with_total(resp.text)
      logger.info(f"[Nike] 검색 '{keyword}' 1페이지 → {len(products)}건 (전체 {total_resources}건)")

      if not products or total_resources <= self.PAGE_SIZE:
        return {"products": products[:max_count], "total": total_resources, "last_error": last_error}

      # 리다이렉트 후 실제 URL로 Referer 설정
      final_url = str(resp.url)
      encoded_keyword = quote(keyword, safe="")

      # 2단계: 추가 페이지를 API로 수집
      anchor = self.PAGE_SIZE
      while len(products) < max_count and anchor < total_resources:
        page_url = (
          f"{self.PAGE_API_URL}"
          f"?path=/kr/w?q%3D{encoded_keyword}"
          f"&searchTerms={encoded_keyword}"
          f"&queryType=PRODUCTS"
          f"&anchor={anchor}"
          f"&count={self.PAGE_SIZE}"
        )
        try:
          api_resp = await client.get(page_url, headers={
            **HEADERS,
            "Accept": "application/json",
            "Referer": final_url,
            "Origin": "https://www.nike.com",
            # 실제 Nike 웹사이트가 사용하는 caller-id (이전값 com.nike.web.product-wall.client 는 오작동)
            "nike-api-caller-id": "com.nike.commerce.nikedotcom.web",
          })
          if api_resp.status_code != 200:
            last_error = f"HTTP {api_resp.status_code} at anchor={anchor}"
            logger.warning(f"[Nike] {last_error}: {api_resp.text[:200]}")
            break
          data = api_resp.json()
          # API 응답에서 totalResources 갱신 (더 정확)
          pages_info = data.get("pages") or {}
          if pages_info.get("totalResources"):
            total_resources = pages_info["totalResources"]
          page_products = self._parse_api_groupings(data.get("productGroupings", []))
          if not page_products:
            last_error = f"빈 productGroupings at anchor={anchor}"
            logger.info(f"[Nike] {last_error}")
            break
          # 중복 제거
          seen = {p["site_product_id"] for p in products}
          new_items = [p for p in page_products if p["site_product_id"] not in seen]
          products.extend(new_items)
          logger.info(f"[Nike] anchor={anchor} → +{len(new_items)}건 (누적 {len(products)}건)")
          # API 응답의 pages.next 가 빈 문자열이면 마지막 페이지
          if pages_info.get("next") == "":
            break
        except Exception as e:
          last_error = f"{type(e).__name__} at anchor={anchor}: {e}"
          logger.warning(f"[Nike] 페이지 수집 실패 {last_error}")
          break
        anchor += self.PAGE_SIZE
        await asyncio.sleep(0.2)

    products = products[:max_count]
    logger.info(f"[Nike] 검색 '{keyword}' 최종 {len(products)}건 수집")
    return {"products": products, "total": total_resources, "last_error": last_error}

  async def get_detail(self, style_color: str) -> dict[str, Any]:
    """상품 상세 조회 — 검색으로 PDP URL 확인 후 PDP 직접 fetch.

    Nike PDP URL은 슬러그 기반이라 styleColor만으로 바로 접근 불가.
    1단계: 검색으로 pdpUrl.url 추출
    2단계: PDP 페이지 fetch → selectedProduct 파싱
    """
    # 1단계: 검색으로 PDP URL + 기본 정보(이름) 확인 (첫 페이지만)
    search_result = await self.search(style_color, max_count=24)
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
  def _parse_search_data_with_total(html: str) -> tuple[list[dict[str, Any]], int]:
    """검색 페이지 __NEXT_DATA__ → (상품 목록, 총 상품수) 반환."""
    nd_match = re.search(
      r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    if not nd_match:
      return [], 0

    try:
      nd = json.loads(nd_match.group(1))
    except json.JSONDecodeError:
      return [], 0

    wall = (
      nd.get("props", {})
      .get("pageProps", {})
      .get("initialState", {})
      .get("Wall", {})
    )
    total_resources = wall.get("pageData", {}).get("totalResources", 0)
    groupings = wall.get("productGroupings", [])
    products = NikeClient._parse_api_groupings(groupings)
    return products, total_resources

  @staticmethod
  def _parse_api_groupings(groupings: list[dict]) -> list[dict[str, Any]]:
    """productGroupings 배열 → 상품 목록 추출 (HTML 파싱 결과 및 API 응답 공용)."""
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
          "video_url": url,  # 나이키 PDP URL 저장 (영상 없으므로 원문링크용으로 활용)
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

    # productGroups에서 해당 styleColor 상품 데이터 추출
    product_groups = page_props.get("productGroups") or []
    prod_data: dict[str, Any] = {}
    if product_groups:
      products_map = product_groups[0].get("products") or {}
      prod_data = products_map.get(style_color) or {}

    # 제목: selectedProduct → productGroups → h1 순으로 fallback
    title = sp.get("title", "")
    subtitle = sp.get("subtitle", "")
    if not title:
      title = prod_data.get("title", "") or sp.get("groupKey", "")
    if not title:
      h1_match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
      if h1_match:
        title = re.sub(r'<[^>]+>', '', h1_match.group(1)).strip()

    name = f"{title} {subtitle}".strip() if subtitle else title

    # 가격
    prices = sp.get("prices") or prod_data.get("prices") or {}
    current_price = prices.get("currentPrice", 0)
    initial_price = prices.get("initialPrice", 0)

    # 이미지: contentImages (갤러리) — selectedProduct 또는 prod_data
    content_images = sp.get("contentImages") or prod_data.get("contentImages") or []
    images = []
    for ci in content_images:
      props = ci.get("properties") or {}
      url = (
        (props.get("squarish") or {}).get("url")
        or (props.get("portrait") or {}).get("url")
      )
      if url and url not in images:
        images.append(url)

    # 색상/제조국
    color = sp.get("colorDescription", "") or prod_data.get("colorDescription", "")
    origin_list = (
      sp.get("manufacturingCountriesOfOrigin")
      or prod_data.get("manufacturingCountriesOfOrigin")
      or []
    )
    origin = ", ".join(origin_list) if origin_list else ""

    # 카테고리/성별
    product_type = sp.get("productType", "") or prod_data.get("productType", "")
    category1 = CAT_MAP.get(product_type, product_type)

    # taxonomyLabels.Gender → 이미 한국어로 제공 ("남성"/"여성"/"키즈" 등)
    taxonomy = prod_data.get("taxonomyLabels") or sp.get("taxonomyLabels") or {}
    gender_labels = taxonomy.get("Gender") or []
    if gender_labels:
      gender_kr = gender_labels[0]
    else:
      # fallback: genders 영문 코드 → 한국어 변환
      gender_en = (sp.get("genders") or prod_data.get("genders") or [""])[0]
      gender_map = {"WOMEN": "여성", "MEN": "남성", "UNISEX": "공용", "KIDS": "키즈"}
      gender_kr = gender_map.get(gender_en, gender_en)

    # 사이즈 옵션: productGroups.sizes → localizedLabel + status(ACTIVE=재고있음)
    sizes_data = prod_data.get("sizes") or []
    if sizes_data:
      options = [
        {"size": s.get("localizedLabel", s.get("label", "")), "stock": 1 if s.get("status") == "ACTIVE" else 0}
        for s in sizes_data
        if s.get("localizedLabel") or s.get("label")
      ]
    else:
      # fallback: HTML label 태그에서 파싱
      size_labels = re.findall(r'<label[^>]*>\s*(\d{3})\s*</label>', html)
      options = [{"size": s, "stock": 1} for s in dict.fromkeys(size_labels)]

    # 상품 정보 섹션 (featuresAndBenefits, productDetails)
    product_info = prod_data.get("productInfo") or {}
    features = product_info.get("featuresAndBenefits") or []
    details = product_info.get("productDetails") or []

    # material: productDetails body 중 '%' 포함 항목만 (소재 비율)
    # ex) "100% 면", "나일론 80% / 폴리에스터 20%"
    material_lines = []
    for section in details:
      for item in (section.get("body") or []):
        if "%" in item:
          material_lines.append(item)
    material = ", ".join(material_lines) if material_lines else ""

    # 품번 (selectedProduct 또는 productGroups에서 styleCode)
    style_code = (
      sp.get("styleCode")
      or prod_data.get("styleCode")
      or (style_color.split("-")[0] if "-" in style_color else style_color)
    )

    # moreInfo: 고시정보 HTML 배열 파싱
    # moreInfo[0]: 제조연월, moreInfo[1]: A/S·세탁방법·품질보증, moreInfo[2]: 제조자/수입자
    more_info = prod_data.get("moreInfo") or sp.get("moreInfo") or []

    def _li_texts(html_parts: list) -> list[str]:
      """HTML 파트 목록에서 li 텍스트(태그 제거) 추출."""
      combined = "".join(html_parts if isinstance(html_parts, list) else [str(html_parts)])
      items = re.findall(r'<li>(.*?)</li>', combined, re.DOTALL)
      return [re.sub(r'<[^>]+>', '', it).strip() for it in items]

    # 제조사: moreInfo[2] → "제조자/수입자" li에서 추출
    manufacturer = "Nike Inc / (유)나이키코리아"  # 기본값
    if len(more_info) > 2:
      for item in _li_texts(more_info[2]):
        if "수입자" in item or "제조자" in item:
          manufacturer = item.split("표기:")[-1].strip() if "표기:" in item else item
          break

    # 세탁방법 / 품질보증: moreInfo[1] → 각 li 시작 키워드로 분류
    care_instructions = ""
    quality_guarantee = ""
    if len(more_info) > 1:
      for item in _li_texts(more_info[1]):
        if item.startswith("세탁방법") and not care_instructions:
          care_instructions = item
        elif item.startswith("품질보증") and not quality_guarantee:
          quality_guarantee = item

    # PDP URL (원문링크): pdpUrl.url 우선, productInfo.url fallback
    pdp_url_obj = prod_data.get("pdpUrl") or {}
    video_url = (
      (pdp_url_obj.get("url") if isinstance(pdp_url_obj, dict) else "")
      or product_info.get("url")
      or ""
    )

    # detail_html: 상품설명 + 슬로건 + 상품특징 + 상품상세
    html_parts = []
    product_description = product_info.get("productDescription") or ""
    reason_to_buy = product_info.get("reasonToBuy") or ""
    if product_description:
      html_parts.append(f"<p>{product_description}</p>")
    if reason_to_buy:
      html_parts.append(f"<p><em>{reason_to_buy}</em></p>")
    for section in features + details:
      header = section.get("header", "")
      body = section.get("body") or []
      if header or body:
        items_html = "".join(f"<li>{item}</li>" for item in body)
        html_parts.append(f"<h3>{header}</h3><ul>{items_html}</ul>")
    detail_html = "".join(html_parts)

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
      "material": material,
      "style_code": style_code,
      "sex": gender_kr,
      "manufacturer": manufacturer,
      "care_instructions": care_instructions,
      "quality_guarantee": quality_guarantee,
      "video_url": video_url,
      "options": options,
      "detail_html": detail_html,
    }
