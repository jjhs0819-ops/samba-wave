"""ESM Plus 판매자 API 클라이언트 (지마켓/옥션 통합).

ESM Trading API v2 (sa2.esmplus.com) 기반.
JWT(HS256) 인증으로 상품 등록/수정/삭제/판매상태/이미지 관리.

지마켓(siteType=2, siteKey=Gmkt, ssiPrefix=G)과
옥션(siteType=1, siteKey=Iac, ssiPrefix=A)을 하나의 클라이언트로 처리.
"""

from __future__ import annotations

import re
import time
from typing import Any

import httpx
import jwt

from backend.domain.samba.proxy.notice_utils import detect_notice_group
from backend.utils.logger import logger


class ESMPlusClient:
    """ESM Plus 판매자 API 클라이언트.

    Args:
      hosting_id: 호스팅사(셀링툴) 마스터 ID (JWT kid)
      secret_key: 호스팅사 시크릿 키 (JWT 서명용)
      seller_id: 판매자 ID (옥션 or 지마켓)
      site: 마켓 구분 ("gmarket" or "auction")
    """

    BASE = "https://sa2.esmplus.com"

    # siteType: 1=옥션, 2=지마켓
    SITE_CONFIG: dict[str, dict[str, Any]] = {
        "gmarket": {
            "siteType": 2,
            "siteKey": "Gmkt",
            "ssiPrefix": "G",
            "label": "지마켓",
        },
        "auction": {"siteType": 1, "siteKey": "Iac", "ssiPrefix": "A", "label": "옥션"},
    }

    def __init__(
        self,
        hosting_id: str,
        secret_key: str,
        seller_id: str,
        site: str = "gmarket",
    ) -> None:
        self.hosting_id = hosting_id
        self.secret_key = secret_key
        self.seller_id = seller_id
        self.site = site
        self.cfg = self.SITE_CONFIG[site]
        self._timeout = httpx.Timeout(30.0, connect=10.0)

    # ------------------------------------------------------------------
    # JWT 토큰 생성
    # ------------------------------------------------------------------

    def _generate_token(self) -> str:
        """HS256 JWT 토큰 생성.

        Header: {"alg":"HS256","typ":"JWT","kid": hostingId}
        Payload: {"iss":"www.esmplus.com","sub":"sell","aud":"sa.esmplus.com","ssi":"G:판매자ID"}
        """
        header = {
            "alg": "HS256",
            "typ": "JWT",
            "kid": self.hosting_id,
        }
        payload = {
            "iss": "www.esmplus.com",
            "sub": "sell",
            "aud": "sa.esmplus.com",
            "iat": int(time.time()),
            "ssi": f"{self.cfg['ssiPrefix']}:{self.seller_id}",
        }
        return jwt.encode(payload, self.secret_key, algorithm="HS256", headers=header)

    def _headers(self) -> dict[str, str]:
        """API 요청 공통 헤더."""
        return {
            "Authorization": f"Bearer {self._generate_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------
    # 공통 API 호출
    # ------------------------------------------------------------------

    async def _call_api(
        self,
        method: str,
        path: str,
        data: dict | None = None,
        params: dict | None = None,
    ) -> dict[str, Any]:
        """ESM Plus API 호출 공통 메서드."""
        url = f"{self.BASE}{path}"
        label = self.cfg["label"]

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.request(
                method,
                url,
                headers=self._headers(),
                json=data,
                params=params,
            )

        # 204 No Content (DELETE 성공 등)
        if resp.status_code == 204:
            return {"resultCode": 0}

        body: dict[str, Any] = {}
        try:
            body = resp.json()
        except Exception:
            pass

        result_code = body.get("resultCode", 0) if body else 0
        if resp.status_code >= 400 or (body and result_code != 0):
            msg = body.get("message") or resp.text[:500]
            logger.error(
                f"[{label}] API 에러 {method} {path}: {resp.status_code} / resultCode={result_code} / {msg}"
            )
            raise RuntimeError(f"[{label}] API 에러 (resultCode={result_code}): {msg}")

        return body

    # ------------------------------------------------------------------
    # 상품 CRUD
    # ------------------------------------------------------------------

    async def register_product(self, data: dict[str, Any]) -> dict[str, Any]:
        """상품 등록 — POST /item/v1/goods"""
        result = await self._call_api("POST", "/item/v1/goods", data=data)
        goods_no = result.get("goodsNo", "")
        site_detail = result.get("siteDetail", {})
        site_key_lower = self.cfg["siteKey"].lower()
        site_goods_no = ""
        for k, v in site_detail.items():
            if k.lower() == site_key_lower:
                site_goods_no = v.get("SiteGoodsNo", "")
                break
        logger.info(
            f"[{self.cfg['label']}] 상품 등록 성공: goodsNo={goods_no}, siteGoodsNo={site_goods_no}"
        )
        return {
            "goodsNo": str(goods_no),
            "siteGoodsNo": site_goods_no,
            **result,
        }

    async def update_product(
        self, goods_no: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """상품 수정 — PUT /item/v1/goods/{goodsNo}"""
        result = await self._call_api("PUT", f"/item/v1/goods/{goods_no}", data=data)
        logger.info(f"[{self.cfg['label']}] 상품 수정 성공: goodsNo={goods_no}")
        return result

    async def get_product(self, goods_no: str) -> dict[str, Any]:
        """상품 조회 — GET /item/v1/goods/{goodsNo}"""
        return await self._call_api("GET", f"/item/v1/goods/{goods_no}")

    async def delete_product(self, goods_no: str) -> dict[str, Any]:
        """상품 삭제 — DELETE /item/v1/goods/{goodsNo}
        주의: 판매중지 상태에서만 삭제 가능
        """
        return await self._call_api("DELETE", f"/item/v1/goods/{goods_no}")

    # ------------------------------------------------------------------
    # 판매상태/가격/재고
    # ------------------------------------------------------------------

    async def update_sell_status(
        self, goods_no: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """판매상태/가격/재고 수정 — PUT /item/v1/goods/{goodsNo}/sell-status"""
        return await self._call_api(
            "PUT", f"/item/v1/goods/{goods_no}/sell-status", data=data
        )

    async def get_sell_status(self, goods_no: str) -> dict[str, Any]:
        """판매상태 조회 — GET /item/v1/goods/{goodsNo}/sell-status"""
        return await self._call_api("GET", f"/item/v1/goods/{goods_no}/sell-status")

    # ------------------------------------------------------------------
    # 이미지
    # ------------------------------------------------------------------

    async def update_images(
        self, goods_no: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """이미지 수정 — POST /item/v1/goods/{goodsNo}/images"""
        return await self._call_api(
            "POST", f"/item/v1/goods/{goods_no}/images", data=data
        )

    # ------------------------------------------------------------------
    # 카테고리
    # ------------------------------------------------------------------

    async def get_categories(self, cat_code: str = "") -> dict[str, Any]:
        """카테고리 조회.
        cat_code 미지정 시 전체 대분류, 지정 시 하위 카테고리.
        """
        path = "/item/v1/categories/site-cats"
        if cat_code:
            path = f"{path}/{cat_code}"
        return await self._call_api("GET", path)

    # ------------------------------------------------------------------
    # 카테고리 트리 전체 수집
    # ------------------------------------------------------------------

    async def fetch_category_tree(
        self,
        delay: float = 0.5,
        exclude_global: bool = True,
    ) -> dict[str, str]:
        """전체 카테고리 트리를 수집하여 {이름경로: 코드} 딕셔너리 반환.

        Args:
          delay: API 호출 간 대기 시간 (초)
          exclude_global: 글로벌/해외 카테고리 제외 여부

        Returns:
          {"남성의류 > 니트 > 풀오버니트": "13290100", ...}
        """
        import asyncio as _aio

        global_keywords = ("글로벌", "Global", "global", "해외", "G로켓", "수출")
        result: dict[str, str] = {}
        api_calls = 0

        async def _walk(parent_code: str, path_prefix: str, depth: int = 0) -> None:
            nonlocal api_calls
            if depth > 5:
                return

            try:
                data = await self._call_api(
                    "GET", f"/item/v1/categories/site-cats/{parent_code}"
                )
                api_calls += 1
            except Exception as e:
                logger.warning(f"[ESM] 카테고리 조회 실패: {parent_code} — {e}")
                return

            subs = data.get("subCats", [])
            for cat in subs:
                name = cat.get("catName", "")
                code = cat.get("catCode", "")
                is_leaf = cat.get("isLeaf", False)

                if exclude_global and any(kw in name for kw in global_keywords):
                    continue

                cat_path = f"{path_prefix} > {name}" if path_prefix else name

                if is_leaf:
                    result[cat_path] = code
                else:
                    await _aio.sleep(delay)
                    await _walk(code, cat_path, depth + 1)

        # 대분류 조회
        try:
            top_data = await self._call_api("GET", "/item/v1/categories/site-cats")
            api_calls += 1
        except Exception as e:
            logger.error(f"[ESM] 대분류 조회 실패: {e}")
            return result

        top_cats = (
            top_data if isinstance(top_data, list) else top_data.get("subCats", [])
        )

        for cat in top_cats:
            name = cat.get("catName", "")
            code = cat.get("catCode", "")

            if exclude_global and any(kw in name for kw in global_keywords):
                continue

            if cat.get("isLeaf", False):
                result[name] = code
            else:
                import asyncio as _aio

                await _aio.sleep(delay)
                await _walk(code, name)

        label = self.cfg["label"]
        logger.info(
            f"[{label}] 카테고리 트리 수집 완료: {len(result)}개 leaf, API {api_calls}회 호출"
        )
        return result

    # ------------------------------------------------------------------
    # 상품 목록 조회
    # ------------------------------------------------------------------

    async def search_products(self, params: dict[str, Any]) -> dict[str, Any]:
        """상품 목록 조회 — POST /item/v1/goods/search (분당 30회 제한)"""
        return await self._call_api("POST", "/item/v1/goods/search", data=params)

    # ------------------------------------------------------------------
    # 데이터 변환 — 상품 dict → ESM Plus API 포맷
    # ------------------------------------------------------------------

    @staticmethod
    def transform_product(
        product: dict[str, Any],
        category_id: str,
        site: str = "gmarket",
    ) -> dict[str, Any]:
        """수집 상품 데이터를 ESM Plus 등록 API 포맷으로 변환.

        Args:
          product: 삼바웨이브 표준 상품 dict
          category_id: ESM Plus 최하위 카테고리 코드
          site: "gmarket" or "auction"
        """
        cfg = ESMPlusClient.SITE_CONFIG[site]
        site_type = cfg["siteType"]
        site_key = cfg["siteKey"]

        # 상품명 (100바이트 제한)
        market_names = product.get("market_names") or {}
        name = (
            market_names.get(cfg["label"])
            or market_names.get("G마켓")
            or market_names.get("옥션")
            or product.get("name", "")
        )
        # 100바이트 제한 — 한글 3바이트 계산
        encoded = name.encode("utf-8")
        if len(encoded) > 100:
            while len(name.encode("utf-8")) > 97:
                name = name[:-1]
            name = name.rstrip() + "..."

        # 가격
        sale_price = int(product.get("sale_price", 0) or 0)
        # 100원 단위 내림
        if sale_price % 100 != 0:
            sale_price = (sale_price // 100) * 100
        if sale_price < 10:
            sale_price = 10

        # 재고
        stock = int(
            product.get("_stock_quantity", 0) or product.get("stock_quantity", 0) or 99
        )
        max_stock = product.get("_max_stock")
        if max_stock:
            stock = min(stock, int(max_stock))
        stock = max(1, min(stock, 99999))

        # 이미지
        images = product.get("images") or []
        basic_img = images[0] if images else ""
        # 프로토콜 보정
        if basic_img and basic_img.startswith("//"):
            basic_img = f"https:{basic_img}"

        image_model: dict[str, Any] = {}
        if basic_img:
            image_model["BasicImage"] = {"URL": basic_img}
        for i, img_url in enumerate(images[1:15], start=1):
            if img_url.startswith("//"):
                img_url = f"https:{img_url}"
            image_model[f"AdditionalImage{i}"] = {"URL": img_url}

        # 상세 HTML
        detail_html = product.get("detail_html", "") or ""
        # 프로토콜 보정
        if detail_html:
            detail_html = re.sub(r'(src=["\'])\/\/', r"\1https://", detail_html)

        # 배송 정보
        delivery_fee_type = product.get("_delivery_fee_type", "FREE")
        delivery_base_fee = int(product.get("_delivery_base_fee", 0) or 0)
        shipping_type = 1  # 택배
        # 계정 설정에서 택배사/발송정책 가져오기
        company_no = int(product.get("_shipping_company_no", 0) or 0)
        dispatch_policy_no = int(product.get("_dispatch_policy_no", 0) or 0)
        place_no = int(product.get("_shipping_place_no", 0) or 0)

        shipping: dict[str, Any] = {
            "type": shipping_type,
        }
        if company_no:
            shipping["companyNo"] = company_no
        if dispatch_policy_no:
            shipping["dispatchPolicyNo"] = dispatch_policy_no
        if place_no:
            shipping["policy"] = {"placeNo": place_no}

        if delivery_fee_type == "PAID" and delivery_base_fee > 0:
            shipping["fee"] = delivery_base_fee

        # 판매기간 (-1=무제한)
        selling_period = int(product.get("_selling_period", -1) or -1)

        # 카테고리
        category_site = [{"siteType": site_type, "catCode": str(category_id)}]

        # 옵션 처리
        options_raw = product.get("options") or []
        option_type = 0  # 기본 미사용
        option_list: list[dict[str, Any]] = []

        if options_raw:
            option_type = 1  # 선택형 옵션
            for opt in options_raw:
                opt_name = opt.get("name", "") or opt.get("option_name", "")
                opt_values = opt.get("values") or opt.get("option_values") or []
                if isinstance(opt_values, str):
                    opt_values = [v.strip() for v in opt_values.split(",") if v.strip()]

                items: list[dict[str, Any]] = []
                for val in opt_values:
                    if isinstance(val, dict):
                        val_name = val.get("name", "") or val.get("value", "")
                        val_price = int(
                            val.get("priceAdjust", 0) or val.get("price_adjust", 0) or 0
                        )
                        val_stock = int(val.get("stock", stock) or stock)
                        val_sold_out = val.get("isSoldOut", False) or val.get(
                            "is_sold_out", False
                        )
                    else:
                        val_name = str(val)
                        val_price = 0
                        val_stock = stock
                        val_sold_out = False

                    items.append(
                        {
                            "optionValue": val_name,
                            "addPrice": val_price,
                            "stockQty": val_stock if not val_sold_out else 0,
                        }
                    )

                if items:
                    option_list.append(
                        {
                            "optionName": opt_name,
                            "optionValues": items,
                        }
                    )

        # 고시정보
        group = detect_notice_group(product)
        official_notice_no = _get_esm_notice_no(group)

        # 브랜드/제조사
        brand = product.get("brand", "")
        manufacturer = product.get("manufacturer", "") or brand

        # 원산지 (기본: 해외 → 상세설명 참조)
        origin = product.get("origin", "")

        # AS 전화번호
        as_phone = product.get("_as_phone", "")

        # API 데이터 구성
        # 주의: ESM Plus API 스펙상 필드명이 "itemAddtionalInfo" (오타 아님)
        # 등록/수정 API: PascalCase 키 (Gmkt, Iac)
        # sell-status API: camelCase 키 (gmkt, iac) — 스펙상 의도적 차이
        data: dict[str, Any] = {
            "itemBasicInfo": {
                "goodsName": {
                    "kor": name,
                },
                "category": {
                    "site": category_site,
                },
                "brand": brand,
                "manufacturer": manufacturer,
            },
            "itemAddtionalInfo": {
                "price": {site_key: sale_price},
                "stock": {site_key: stock},
                "sellingPeriod": {site_key: selling_period},
                "shipping": shipping,
                "images": {
                    "basicImgURL": basic_img,
                },
                "descriptions": {
                    "kor": {
                        "html": detail_html,
                    },
                },
            },
        }

        # 추가 이미지 (이미지 모델은 등록 후 별도 API로 설정)
        if len(images) > 1:
            data["_pending_images"] = image_model

        # 옵션
        if option_list:
            data["itemAddtionalInfo"]["optionType"] = option_type
            data["itemAddtionalInfo"]["options"] = option_list

        # 고시정보
        if official_notice_no:
            data["itemAddtionalInfo"]["officialNoticeNo"] = official_notice_no

        # 원산지
        if origin:
            data["itemBasicInfo"]["origin"] = origin

        # AS 전화번호
        if as_phone:
            data["itemAddtionalInfo"]["asPhone"] = as_phone

        # 관리코드 (소싱처 상품 ID)
        source_product_id = product.get("source_product_id", "")
        if source_product_id:
            data["itemBasicInfo"]["managedCode"] = str(source_product_id)[:50]

        return data


# ------------------------------------------------------------------
# 고시정보 번호 매핑 (ESM Plus 전용)
# ------------------------------------------------------------------

# ESM Plus 고시정보 그룹 번호 (officialNoticeNo)
# 실제 번호는 GET /item/v1/official-notice/groups 로 조회 가능
# 아래는 일반적 매핑 (마켓에서 조회 후 갱신 필요)
_ESM_NOTICE_MAP: dict[str, int] = {
    "wear": 1,  # 의류
    "shoes": 2,  # 신발
    "bag": 3,  # 가방
    "accessories": 4,  # 패션잡화
    "cosmetic": 5,  # 화장품
    "food": 6,  # 식품
    "electronics": 7,  # 전자제품
    "etc": 35,  # 기타
}


def _get_esm_notice_no(group: str) -> int:
    """고시정보 그룹 → ESM Plus 고시정보 번호."""
    return _ESM_NOTICE_MAP.get(group, 35)


# ------------------------------------------------------------------
# 카테고리 매핑 캐시 및 조회
# ------------------------------------------------------------------

# 메모리 캐시 — 서버 기동 시 JSON 파일에서 로드
_cat_cache: dict[str, dict[str, str]] = {}


def _load_cat_mapping(name: str) -> dict[str, str]:
    """카테고리 매핑 JSON 파일 로드 (캐시 적용)."""
    if name in _cat_cache:
        return _cat_cache[name]

    import json
    from pathlib import Path

    mapping_dir = Path(__file__).resolve().parent.parent / "category"
    filepath = mapping_dir / f"esm_{name}.json"

    if not filepath.exists():
        logger.warning(f"[ESM] 카테고리 매핑 파일 없음: {filepath}")
        return {}

    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    _cat_cache[name] = data
    logger.info(f"[ESM] 카테고리 매핑 로드: {name} ({len(data)}개)")
    return data


def esm_map_category(cat_code: str, from_site: str, to_site: str) -> str:
    """옥션↔지마켓 카테고리 코드 변환.

    Args:
      cat_code: 원본 카테고리 코드
      from_site: "auction" or "gmarket"
      to_site: "auction" or "gmarket"

    Returns:
      변환된 카테고리 코드 (매핑 없으면 빈 문자열)
    """
    if from_site == to_site:
        return cat_code

    if from_site == "auction" and to_site == "gmarket":
        mapping = _load_cat_mapping("auction_to_gmarket")
    elif from_site == "gmarket" and to_site == "auction":
        mapping = _load_cat_mapping("gmarket_to_auction")
    else:
        return ""

    return mapping.get(cat_code, "")


def esm_find_category_by_path(path: str, site: str) -> str:
    """이름경로로 카테고리 코드 조회.

    Args:
      path: "남성의류 > 니트 > 풀오버니트"
      site: "auction" or "gmarket"

    Returns:
      카테고리 코드 (없으면 빈 문자열)
    """
    tree_name = "auction_cats" if site == "auction" else "gmarket_cats"
    tree = _load_cat_mapping(tree_name)
    return tree.get(path, "")
