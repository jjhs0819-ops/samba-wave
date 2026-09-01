"""패션플러스 요청 페이로드 조립 + 가격·재고 정규화.

패플 제약을 여기서 전부 흡수해 플러그인은 흐름만 담당하게 한다.
- Err-Upt-110: 소비자가 >= 판매가 x 0.9
- Err-Dat-104/105: 판매가 100원 미만 불가
- ScmOptionUpt: 재고 최대 200
"""

from __future__ import annotations

import math
from typing import Any

MAX_STOCK = 200
MIN_SALE_PRICE = 100
_CONSUMER_RATIO = 0.9
_MAX_IMAGES = 4


def normalize_prices(
    sale_price: Any, consumer_price: Any = None
) -> tuple[int, int] | None:
    """(판매가, 소비자가) 를 패플 제약에 맞춘다. 전송 불가면 None."""
    try:
        sale = int(float(sale_price))
    except (TypeError, ValueError):
        return None
    if sale < MIN_SALE_PRICE:
        return None
    try:
        consumer = int(float(consumer_price)) if consumer_price else 0
    except (TypeError, ValueError):
        consumer = 0
    floor = math.ceil(sale * _CONSUMER_RATIO)
    return sale, max(consumer, floor)


def clamp_stock(qty: Any) -> int:
    """재고를 0..200 으로 자른다."""
    try:
        n = int(float(qty))
    except (TypeError, ValueError):
        return 0
    return max(0, min(n, MAX_STOCK))


def option_key(option: dict) -> str:
    """색상|사이즈 정규화 키. OptID 매핑의 키로 쓴다."""
    color = str(option.get("color") or "").strip().upper()
    size = str(option.get("size") or "").strip().upper()
    return f"{color}|{size}"


def build_goods_add(
    product: dict, category_id: str, brand_id: str, sender_code: str
) -> dict:
    """GoodsAdd 요청 본문. 필수값이 없으면 ValueError 로 즉시 실패시킨다.

    매핑이 없는 채로 전송해 봐야 패플이 거절하고 재시도만 낭비한다.
    (신세계몰 카테고리 미매핑 즉시실패와 같은 규약)
    """
    if not brand_id:
        raise ValueError("패션플러스 BrandId 매핑 없음")
    if not category_id:
        raise ValueError("패션플러스 카테고리 매핑 없음")

    prices = normalize_prices(product.get("sale_price"), product.get("consumer_price"))
    if prices is None:
        raise ValueError(f"패션플러스 전송 불가 판매가: {product.get('sale_price')!r}")
    sale, consumer = prices

    images = [str(u) for u in (product.get("images") or []) if u][:_MAX_IMAGES]
    if not images:
        raise ValueError("패션플러스 대표이미지 없음")

    name = str(product.get("name") or "").strip()
    if not name:
        raise ValueError("패션플러스 상품명 없음")

    body: dict[str, Any] = {
        "ItemNo": str(product.get("site_product_id") or product.get("id") or ""),
        "ItemName": name,
        "DisplayItemName": name,
        "SalePrice": sale,
        "ConsumerPrice": consumer,
        "BrandId": str(brand_id),
        "Category1": str(category_id),
        "Description": str(product.get("detail_html") or ""),
        "SenderCode": str(sender_code or ""),
    }
    for idx, url in enumerate(images, start=1):
        body[f"ImageURL{idx}"] = url
    return body


def build_scm_option_upt(
    item_id: str,
    option_ids: dict[str, int],
    options: list[dict],
    update_price: bool = False,
) -> list[dict]:
    """ScmOptionUpt 요청 행 목록. OptID 를 모르는 옵션은 건너뛴다."""
    rows: list[dict] = []
    for option in options or []:
        opt_id = option_ids.get(option_key(option))
        if not opt_id:
            continue
        row: dict[str, Any] = {
            "ItemId": str(item_id),
            "OptID": opt_id,
            "StockQty": clamp_stock(option.get("stock")),
            "IsOptionPriceUpdate": 1 if update_price else 0,
        }
        if update_price:
            row["OptPrice"] = int(float(option.get("option_price") or 0))
        rows.append(row)
    return rows
