"""패션플러스 요청 페이로드 조립 + 가격·재고 정규화.

패플 제약을 여기서 전부 흡수해 플러그인은 흐름만 담당하게 한다.
- Err-Upt-110: 소비자가 >= 판매가 x 0.9
- Err-Dat-104/105: 판매가 100원 미만 불가
- ScmOptionUpt: 재고 최대 200
"""

from __future__ import annotations

import math
from typing import Any

from backend.utils.logger import logger

MAX_STOCK = 200
MIN_SALE_PRICE = 100
_CONSUMER_RATIO = 0.9
_MAX_IMAGES = 4


def normalize_prices(
    sale_price: Any, consumer_price: Any = None
) -> tuple[int, int] | None:
    """(판매가, 소비자가) 를 패플 제약에 맞춘다. 전송 불가면 None.

    소비자가(정가) 하한은 ceil(판매가 / 0.9) — 정가가 항상 판매가 이상이면서
    패플 제약(ConsumerPrice >= SalePrice x 0.9)도 자동으로 만족한다.
    (곱하기 0.9 로 내리면 정가가 판매가보다 싼 말이 안 되는 값이 나간다)
    """
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
    floor = math.ceil(sale / _CONSUMER_RATIO)
    return sale, max(consumer, floor)


def extract_consumer_price(product: dict) -> Any:
    """상품 dict 에서 정가 입력을 꺼낸다.

    수집 모델의 정가 필드는 original_price 다 (collector/model.py).
    consumer_price 는 모델에 없지만 외부 유입 dict 대비 폴백으로 남긴다.
    """
    return product.get("original_price") or product.get("consumer_price")


def clamp_stock(qty: Any) -> int:
    """재고를 0..200 으로 자른다."""
    try:
        n = int(float(qty))
    except (TypeError, ValueError):
        return 0
    return max(0, min(n, MAX_STOCK))


def option_key(option: dict) -> str:
    """색상|사이즈 정규화 키. OptID 매핑의 키로 쓴다.

    색상·사이즈가 모두 비면(원사이즈 등) 서로 다른 옵션이 같은 키("|")로
    수렴해 OptID 매핑이 뒤섞인다 — 이때는 보조값(name → id)을 키로 쓴다.
    id 는 정수 0 도 유효한 식별자라 falsy 판정이 아니라 is not None 로 본다.
    보조값도 없으면 빈 문자열을 돌려 "매핑 불가"로 취급되게 한다.
    """
    color = str(option.get("color") or "").strip().upper()
    size = str(option.get("size") or "").strip().upper()
    if color or size:
        return f"{color}|{size}"
    name = str(option.get("name") or "").strip().upper()
    if name:
        return name
    ident = option.get("id")
    if ident is not None:
        return str(ident).strip().upper()
    return ""


def has_uneven_option_price(options: list[dict]) -> bool:
    """옵션별 가격(option_price)이 서로 다른 상품인지 판정한다.

    옵션가 불균일 상품은 대표가 하나로 전송되면 비싼 옵션이 싸게 팔리는
    역마진이 난다 — 신세계몰·롯데홈·포이즌에서 반복된 사고 유형(설계서 §4.4-3).
    값이 아예 없거나(키 없음·해석 불가) 전부 같으면 False.
    """
    values: set[int] = set()
    for option in options or []:
        if "option_price" not in option:
            continue
        try:
            values.add(int(float(option["option_price"])))
        except (TypeError, ValueError):
            # 해석 불가 값은 판정 대상에서 제외 — 전송 단계(build_scm_option_upt)가
            # 별도로 스킵·경고 처리한다
            continue
    return len(values) > 1


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

    if has_uneven_option_price(product.get("options") or []):
        raise ValueError("패션플러스 옵션별 가격이 달라 전송 제외")

    prices = normalize_prices(product.get("sale_price"), extract_consumer_price(product))
    if prices is None:
        raise ValueError(f"패션플러스 전송 불가 판매가: {product.get('sale_price')!r}")
    sale, consumer = prices

    images = [str(u) for u in (product.get("images") or []) if u][:_MAX_IMAGES]
    if not images:
        raise ValueError("패션플러스 대표이미지 없음")

    name = str(product.get("name") or "").strip()
    if not name:
        raise ValueError("패션플러스 상품명 없음")

    item_no = str(product.get("site_product_id") or product.get("id") or "").strip()
    if not item_no:
        raise ValueError("패션플러스 ItemNo(상품 식별자) 없음")

    body: dict[str, Any] = {
        "ItemNo": item_no,
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
    """ScmOptionUpt 요청 행 목록.

    - OptID 매핑이 없는 옵션은 건너뛰되, 무음으로 사라지지 않게
      스킵된 키 목록·개수를 경고 로그로 남긴다. (OptID 0 은 유효한 매핑)
    - update_price=True 인데 option_price 키가 없거나 숫자 해석 불가면
      0 으로 날조하지 않고 그 옵션을 제외한다 — 역마진 사고 방지.
      (패플 샘플상 OptPrice 0 자체는 적법 — 값이 있으면 0 도 그대로 전송)
    """
    rows: list[dict] = []
    skipped_unmapped: list[str] = []
    skipped_price: list[str] = []
    for option in options or []:
        key = option_key(option)
        opt_id = option_ids.get(key) if key else None
        if opt_id is None:
            skipped_unmapped.append(key or "(키 산출 불가)")
            continue
        row: dict[str, Any] = {
            "ItemId": str(item_id),
            "OptID": opt_id,
            "StockQty": clamp_stock(option.get("stock")),
            "IsOptionPriceUpdate": 1 if update_price else 0,
        }
        if update_price:
            if "option_price" not in option:
                skipped_price.append(key)
                continue
            try:
                row["OptPrice"] = int(float(option["option_price"]))
            except (TypeError, ValueError):
                skipped_price.append(key)
                continue
        rows.append(row)
    if skipped_unmapped:
        logger.warning(
            "[패션플러스] OptID 매핑 없는 옵션 %d건 스킵 (ItemId=%s): %s",
            len(skipped_unmapped), item_id, skipped_unmapped,
        )
    if skipped_price:
        logger.warning(
            "[패션플러스] 옵션가 없음/해석불가 옵션 %d건 제외 (ItemId=%s): %s",
            len(skipped_price), item_id, skipped_price,
        )
    return rows
