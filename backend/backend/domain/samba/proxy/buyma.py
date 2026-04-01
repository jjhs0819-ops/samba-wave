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
        name = product.get("name") or ""
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
