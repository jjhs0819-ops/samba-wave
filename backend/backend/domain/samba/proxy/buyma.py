"""바이마(BUYMA) 상품 등록 클라이언트 - CSV 생성 방식.

바이마는 공개 API가 없으므로 CSV 파일을 생성하여
셀러센터에서 일괄 업로드하는 방식으로 운영한다.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from backend.utils.logger import logger


# CSV 컬럼 정의 (바이마 일괄등록 템플릿)
CSV_COLUMNS = [
    "商品管理番号",
    "商品名",
    "ブランドID",
    "カテゴリID",
    "価格",
    "参考価格",
    "買付地",
    "発送地",
    "配送方法",
    "配送日数",
    "商品コメント",
    "色サイズ",
    "商品画像1",
    "商品画像2",
    "商品画像3",
    "商品画像4",
    "商品画像5",
]


class BuymaClient:
    """바이마 CSV 생성 클라이언트."""

    def __init__(self, seller_id: str = "", **kwargs: Any) -> None:
        self.seller_id = seller_id

    # ------------------------------------------------------------------
    # 상품 변환
    # ------------------------------------------------------------------

    @staticmethod
    def transform_product(
        product: dict[str, Any],
        category_id: str,
        account_settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """CollectedProduct → 바이마 CSV 행 변환."""
        settings = account_settings or {}
        # 바이마=일본 마켓 → 일문상품명(name_ja) 우선. 없으면 한글 name 폴백
        # (일문명 미설정 시 등록은 BuymaPlugin.execute에서 차단됨)
        name = product.get("name_ja") or product.get("name") or ""
        sale_price = int(
            product.get("_final_sale_price") or product.get("sale_price") or 0
        )
        original_price = int(product.get("original_price") or sale_price)
        images = product.get("images") or []
        detail_html = product.get("detail_html") or f"<p>{name}</p>"
        brand = product.get("brand") or ""

        # 옵션 → 색サイズ 문자열 (색상:サイズ1,サイズ2 형식)
        options = product.get("options") or []
        color = product.get("color") or ""
        size_parts = []
        for opt in options:
            opt_name = opt.get("name") or opt.get("size") or ""
            if opt_name and not opt.get("isSoldOut", False):
                size_parts.append(opt_name)
        color_size = f"{color}:{','.join(size_parts)}" if size_parts else color

        # 이미지 (최대 5장)
        img_dict: dict[str, str] = {}
        for i, url in enumerate(images[:5]):
            img_dict[f"商品画像{i + 1}"] = url

        row: dict[str, Any] = {
            "商品管理番号": product.get("id") or product.get("site_product_id") or "",
            "商品名": name,
            "ブランドID": brand,
            "カテゴリID": category_id,
            "価格": sale_price,
            "参考価格": original_price,
            "買付地": settings.get("buyingCountry", "韓国"),
            "発送地": settings.get("shippingCountry", "韓国"),
            "配送方法": settings.get("deliveryMethod", "国際配送"),
            "配送日数": settings.get("deliveryDays", "7-14"),
            "商品コメント": detail_html,
            "色サイズ": color_size,
            **img_dict,
        }

        return row

    # ------------------------------------------------------------------
    # CSV 생성
    # ------------------------------------------------------------------

    @staticmethod
    def generate_csv(products: list[dict[str, Any]]) -> str:
        """상품 목록 → CSV 문자열 생성 (UTF-8 BOM)."""
        output = io.StringIO()
        output.write("\ufeff")  # UTF-8 BOM

        writer = csv.DictWriter(
            output,
            fieldnames=CSV_COLUMNS,
            extrasaction="ignore",
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        for p in products:
            writer.writerow(p)

        csv_str = output.getvalue()
        logger.info(f"[바이마] CSV 생성 완료: {len(products)}건")
        return csv_str

    # ------------------------------------------------------------------
    # 상품 등록 (CSV 행 반환)
    # ------------------------------------------------------------------

    async def register_product(
        self, product: dict[str, Any], category_id: str
    ) -> dict[str, Any]:
        """상품 등록 — API 없으므로 CSV 행 데이터 반환."""
        row = self.transform_product(product, category_id)
        logger.info(f"[바이마] CSV 행 생성: {row.get('商品管理番号')}")
        return {
            "success": True,
            "csv_row": row,
            "message": "바이마는 API가 없습니다. CSV를 다운로드하여 셀러센터에서 업로드하세요.",
        }

    async def update_product(
        self, product_no: str, product: dict[str, Any]
    ) -> dict[str, Any]:
        """상품 수정 — CSV 행 반환."""
        return {
            "success": True,
            "message": "바이마는 API가 없습니다. CSV 재생성 후 셀러센터에서 업로드하세요.",
        }

    async def delete_product(self, product_no: str) -> dict[str, Any]:
        """상품 삭제 — 안내만 반환."""
        return {
            "success": True,
            "message": "바이마는 API가 없습니다. 셀러센터에서 직접 삭제하세요.",
        }


class BuymaExportError(Exception):
    """바이마 CSV 생성 에러."""

    pass


# ======================================================================
# BUYMA PS-API (Personal Shopper API) 클라이언트
# ======================================================================

from datetime import date, timedelta

import httpx

from backend.domain.samba.proxy import buyma_mapping as bm


class BuymaApiError(Exception):
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"BUYMA API {status}: {body[:200]}")


class BuymaApiClient:
    """BUYMA PS-API 클라이언트 — OAuth 토큰교환 + 상품/재고 등록.

    샌드박스에서 상의·아우터·신발 201 검증된 스키마 사용.
    헤더: X-Buyma-Personal-Shopper-Api-Access-Token
    rate limit: 상품 API 2,500/24h, 전체 5,000/h.
    """

    SANDBOX_BASE = "https://sandbox.personal-shopper-api.buyma.com"
    PROD_BASE = "https://personal-shopper-api.buyma.com"

    def __init__(
        self,
        access_token: str = "",
        *,
        sandbox: bool = True,
        client_id: str = "",
        client_secret: str = "",
    ) -> None:
        self.access_token = access_token
        self.sandbox = sandbox
        self.base = self.SANDBOX_BASE if sandbox else self.PROD_BASE
        self.client_id = client_id
        self.client_secret = client_secret

    # ------------------------------------------------------------------
    # OAuth
    # ------------------------------------------------------------------
    @classmethod
    async def exchange_code(
        cls,
        code: str,
        redirect_uri: str,
        client_id: str,
        client_secret: str,
        *,
        sandbox: bool = True,
    ) -> dict[str, str]:
        """authorization code → access/refresh token."""
        base = cls.SANDBOX_BASE if sandbox else cls.PROD_BASE
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base}/oauth/token",
                json={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
            )
        if resp.status_code not in (200, 201):
            raise BuymaApiError(resp.status_code, resp.text)
        data = resp.json()
        return {
            "access_token": data.get("access_token", ""),
            "refresh_token": data.get("refresh_token", ""),
        }

    @classmethod
    def authorize_url(
        cls, client_id: str, redirect_uri: str, state: str, *, sandbox: bool = True
    ) -> str:
        base = cls.SANDBOX_BASE if sandbox else cls.PROD_BASE
        from urllib.parse import urlencode

        q = urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "state": state,
            }
        )
        return f"{base}/oauth/authorize?{q}"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Buyma-Personal-Shopper-Api-Access-Token": self.access_token,
        }

    # ------------------------------------------------------------------
    # transform: CollectedProduct dict → products.json payload
    # ------------------------------------------------------------------
    @staticmethod
    def transform_product(
        product: dict[str, Any],
        *,
        control: str = "publish",
        account_settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        name = product.get("name_ja") or product.get("name") or ""
        brand = product.get("brand") or ""
        cat_id = bm.map_category(
            product.get("category1") or "",
            product.get("category2") or "",
            product.get("category3") or "",
        )
        ship_id, ship_krw, _ = bm.shipping_for_category(cat_id)
        sourcing_krw = int(
            product.get("_final_sale_price") or product.get("sale_price") or 0
        )
        color_id, color_val = bm.map_color(
            product.get("color") or product.get("name") or ""
        )
        images = [
            {"path": u, "position": i + 1}
            for i, u in enumerate((product.get("images") or [])[:20])
            if u
        ]

        # 상품 단위 품절 — 무신사 goodsSaleType=STAND_BY_SALE 등은 상품 전체가
        # 구매 불가인데도 개별 옵션의 isSoldOut 은 False 로 내려온다. 옵션만 보면
        # 품절 상품이 "판매 가능"으로 등록되므로 상품 단위 상태를 함께 본다.
        product_sold_out = bool(
            product.get("isOutOfStock")
            or product.get("is_out_of_stock")
            or (product.get("sale_status") or product.get("saleStatus")) == "sold_out"
        )

        # options → 사이즈 추출 + 재고
        options = [
            {"type": "color", "master_id": color_id, "position": 1, "value": color_val}
        ]
        variants: list[dict[str, Any]] = []
        pos = 2
        for size_label, sold_out in _iter_sizes(product):
            mid = bm.size_master(size_label, cat_id)
            if mid is None:
                continue
            options.append(
                {"type": "size", "master_id": mid, "position": pos, "value": size_label}
            )
            pos += 1
            variants.append(
                {
                    "options": [
                        {"type": "color", "value": color_val},
                        {"type": "size", "value": size_label},
                    ],
                    "stock_type": (
                        "out_of_stock"
                        if (sold_out or product_sold_out)
                        else "purchase_for_order"
                    ),
                    "order_quantity": 1,
                }
            )

        # 품번(ブランド品番) — 바이마 구매자는 품번으로 검색하므로 누락되면
        # /r/{품번} 검색 결과에 아예 노출되지 않는다. CSV(buyma_bulk)·직접등록
        # (buyma_direct)과 동일하게 소싱 품번을 넣는다.
        style = bm.clean_style_no(
            product.get("style_code") or product.get("model_no") or ""
        )

        until = (date.today() + timedelta(days=60)).strftime("%Y/%m/%d")
        return {
            "product": {
                "reference_number": str(
                    product.get("id") or product.get("site_product_id") or ""
                ),
                "control": control,
                "name": name[:60],
                "comments": (
                    product.get("detail_html")
                    or f"100%正規品・新品。韓国より発送。\n{name}"
                )[:3000],
                "brand_id": bm.brand_id(brand),
                "category_id": cat_id,
                "price": bm.price_to_yen(sourcing_krw, ship_krw),
                "available_until": until,
                "buying_area_id": bm.KOREA_AREA_ID,
                "shipping_area_id": bm.KOREA_AREA_ID,
                "duty": "included",  # 관세부담없음
                "images": images,
                "shipping_methods": [{"shipping_method_id": ship_id}],
                "style_numbers": [{"number": style}] if style else [],
                "options": options,
                "variants": variants,
            }
        }

    # ------------------------------------------------------------------
    # 상품 등록/수정/삭제 (products.json, control 필드)
    # ------------------------------------------------------------------
    async def register_product(
        self, product: dict[str, Any], *, control: str = "publish"
    ) -> dict[str, Any]:
        payload = self.transform_product(product, control=control)
        prod = payload["product"]
        if not prod["name"]:
            return {
                "success": False,
                "error_type": "missing_name_ja",
                "message": "일문 상품명 없음",
            }
        if not prod["variants"]:
            return {
                "success": False,
                "error_type": "no_variants",
                "message": "매핑된 사이즈 없음",
            }
        # 전 사이즈 품절인데 등록하면 구매 불가 상품이 노출된다. 주문이 들어오면
        # 매입 자체가 불가능해 강제취소(매입성공률 하락)로 직결되므로 차단한다.
        if not any(
            v.get("stock_type") == "purchase_for_order" for v in prod["variants"]
        ):
            return {
                "success": False,
                "error_type": "all_sold_out",
                "message": "판매 가능한 사이즈 없음(전 사이즈 품절)",
            }
        # 이미지가 한 장도 없으면 상품 페이지가 성립하지 않는다.
        if not prod["images"]:
            return {
                "success": False,
                "error_type": "no_images",
                "message": "등록 가능한 이미지 없음",
            }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base}/api/v1/products.json",
                json=payload,
                headers=self._headers(),
            )
        if resp.status_code == 429:
            return {
                "success": False,
                "error_type": "rate_limited",
                "message": resp.text[:200],
            }
        if resp.status_code not in (200, 201):
            return {
                "success": False,
                "error_type": "api_error",
                "message": f"HTTP {resp.status_code}: {resp.text[:300]}",
            }
        data = resp.json()
        # 상품ID는 webhook으로 옴. reference_number로 추적.
        logger.info(
            f"[바이마API] 등록 수락 ref={prod['reference_number']} uid={data.get('request_uid')}"
        )
        return {
            "success": True,
            "reference_number": prod["reference_number"],
            "request_uid": data.get("request_uid"),
            "message": "등록 요청 수락(상품ID는 webhook 수신)",
        }

    async def set_control(self, reference_number: str, control: str) -> dict[str, Any]:
        """control=suspend(정지)/delete(삭제)/publish(재개)."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base}/api/v1/products.json",
                json={
                    "product": {
                        "reference_number": reference_number,
                        "control": control,
                    }
                },
                headers=self._headers(),
            )
        if resp.status_code not in (200, 201):
            return {
                "success": False,
                "message": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }
        return {"success": True, "message": f"control={control} 수락"}

    async def update_variants(
        self, reference_number: str, variants: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """재고/판매가능 수정 (자동품절). variants: [{options, stock_type, order_quantity}]."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base}/api/v1/products/variants.json",
                json={
                    "product": {
                        "reference_number": reference_number,
                        "variants": variants,
                    }
                },
                headers=self._headers(),
            )
        if resp.status_code not in (200, 201):
            return {
                "success": False,
                "message": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }
        return {"success": True, "message": "재고 수정 수락"}


def _iter_sizes(product: dict[str, Any]):
    """CollectedProduct.options → [(size_label, sold_out), ...].

    옵션 name이 '색 / 사이즈' 조합이면 사이즈 파트 추출, 단일이면 그대로.
    """
    group_names = product.get("option_group_names") or []
    size_idx = None
    for i, g in enumerate(group_names):
        if "사이즈" in (g or "") or "size" in (g or "").lower():
            size_idx = i
            break
    seen = set()
    for opt in product.get("options") or []:
        nm = (opt.get("name") or opt.get("size") or "").strip()
        if not nm:
            continue
        if "/" in nm:
            parts = [p.strip() for p in nm.split("/")]
            label = (
                parts[size_idx]
                if (size_idx is not None and size_idx < len(parts))
                else parts[-1]
            )
        else:
            label = nm
        if label in seen:
            continue
        seen.add(label)
        yield label, bool(opt.get("isSoldOut", False))
