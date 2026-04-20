"""네이버스토어 상품 데이터 파서 모듈.

확장앱이 탭 컨텍스트에서 가져온 raw JSON을 worker 호환 snake_case 스키마로 변환.
`NaverStoreSourcingClient` 가 import하여 사용.
"""

from __future__ import annotations

import re
from typing import Any


def _clamp_stock(v: Any) -> int:
    """네이버 consumer API의 9999(무한) placeholder를 99로 제한.

    Why: 네이버는 재고 '충분' 상태를 9999로 반환하지만 쌈바 UI/마켓 전송은 99로 표현.
    How to apply: 실재고(1~998) 및 품절(0)은 그대로 유지, 999 이상만 99로 클램프.
    """
    try:
        n = int(v or 0)
    except (TypeError, ValueError):
        return 0
    return 99 if n >= 999 else n


def _parse_detail_product(
    d: dict[str, Any], product_id: str, store_name: str
) -> dict[str, Any]:
    """상세 API 응답(product 객체)을 worker 호환 snake_case 스키마로 파싱.

    확장앱이 탭 컨텍스트에서 /i/v2/channels/{uid}/products/{pid} API로 가져온 raw JSON을
    받아 표준 상품 필드로 변환한다. subprocess 스크립트의 파싱 로직과 동치.
    """
    BASE_URL = "https://smartstore.naver.com"
    name = d.get("name") or d.get("dispName", "")

    rep_imgs: list[str] = []
    opt_imgs: list[str] = []
    for img in d.get("productImages") or []:
        url = img.get("url", "")
        if not url:
            continue
        t = img.get("imageType", "")
        if t == "REPRESENTATIVE":
            rep_imgs.append(url)
        elif t == "OPTIONAL":
            opt_imgs.append(url)
    thumbnail = rep_imgs[0] if rep_imgs else ""

    detail_html = ""
    dc = d.get("detailContents")
    if isinstance(dc, dict):
        detail_html = dc.get("detailContentText", "") or ""
    _detail_extracted: list[str] = []
    if detail_html:
        _detail_extracted = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', detail_html)
        _detail_extracted = [u for u in _detail_extracted if u.startswith("http")]

    # images: 대표 + 추가
    # detail_images: 상세HTML URL 원본 그대로 (dedup X) + padding
    # - worker.py(2101)는 len(detail_images) > len(images) 일 때만 detail_images 유지
    # - cafe24 markets 플러그인은 set(detail_images) 문자열 매칭으로 images 필터링
    # → 양말 등 상세 HTML 짧은 상품도 덮어쓰기 방지하려면 padding 필요
    # → padding URL은 cafe24 _is_allowed_image 필터에 자연 차단돼 상세페이지에 렌더되지 않음
    images = rep_imgs + opt_imgs
    detail_imgs: list[str] = list(_detail_extracted)
    _pad_needed = max(0, len(images) + 1 - len(detail_imgs))
    if _pad_needed > 0:
        detail_imgs.extend(
            [f"https://samba-naver-pad-{i}.internal/p.jpg" for i in range(_pad_needed)]
        )

    sale_price = d.get("salePrice", 0) or 0
    benefits = d.get("benefitsView") or {}
    disc_price = benefits.get("discountedSalePrice", 0) or sale_price
    disc_rate = benefits.get("discountedRatio", 0) or 0

    cat_info = d.get("category") or {}
    cat_str = (
        cat_info.get("wholeCategoryName", "") if isinstance(cat_info, dict) else ""
    )
    cat_parts = cat_str.split(">") if cat_str else []
    cat1 = cat_parts[0].strip() if len(cat_parts) > 0 else ""
    cat2 = cat_parts[1].strip() if len(cat_parts) > 1 else ""
    cat3 = cat_parts[2].strip() if len(cat_parts) > 2 else ""
    cat4 = cat_parts[3].strip() if len(cat_parts) > 3 else ""

    search_info = d.get("naverShoppingSearchInfo") or {}
    brand = search_info.get("brandName", "") or ""
    manufacturer = search_info.get("manufacturerName", "") or ""
    model_number = (
        search_info.get("modelName", "") or search_info.get("modelNumber", "") or ""
    )

    origin_info = d.get("originAreaInfo") or {}
    origin = origin_info.get("content", "") if isinstance(origin_info, dict) else ""

    material = ""
    color = ""
    sex = ""
    season = ""

    def _collect_notice_pairs(obj: Any, out: list[tuple[str, str]]) -> None:
        if isinstance(obj, list):
            for item in obj:
                _collect_notice_pairs(item, out)
        elif isinstance(obj, dict):
            title = obj.get("title") or obj.get("name") or obj.get("label")
            content = obj.get("content") or obj.get("value") or obj.get("text")
            if isinstance(title, str) and isinstance(content, (str, int, float)):
                out.append((title, str(content)))
                return
            for k, v in obj.items():
                if isinstance(v, (dict, list)):
                    _collect_notice_pairs(v, out)
                elif isinstance(v, (str, int, float)):
                    out.append((str(k), str(v)))

    notice = d.get("productInfoProvidedNoticeView") or {}
    pairs: list[tuple[str, str]] = []
    _collect_notice_pairs(notice, pairs)

    for k, v in pairs:
        k_low = str(k).lower()
        v_str = str(v).strip() if v else ""
        if not v_str or v_str in ("해당없음", "상세설명참조", "상세페이지참조"):
            continue
        if "재질" in k_low or "material" in k_low or "소재" in k_low:
            material = material or v_str
        elif "색상" in k_low or "color" in k_low:
            color = color or v_str
        elif "성별" in k_low or "sex" in k_low:
            sex = sex or v_str
        elif "시즌" in k_low or "season" in k_low or "계절" in k_low:
            season = season or v_str
        elif "품번" in k_low or "model" in k_low:
            model_number = model_number or v_str
        elif "원산지" in k_low or "제조국" in k_low:
            origin = origin or v_str

    if not sex:
        sex = "남녀공용"
    if not season:
        season = "사계절"

    options_list: list[dict[str, Any]] = []
    for combo in d.get("optionCombinations") or []:
        if not isinstance(combo, dict):
            continue
        opt_names: list[str] = []
        for i in range(1, 4):
            val = combo.get(f"optionName{i}", "")
            if val:
                opt_names.append(str(val))
        display = " / ".join(opt_names)
        stock = _clamp_stock(combo.get("stockQuantity", 0))
        options_list.append(
            {
                "name": display,
                "price": combo.get("price", 0) or 0,
                "stock": stock,
                "isSoldOut": stock <= 0,
            }
        )

    delivery_info = d.get("productDeliveryInfo") or {}
    fee_type = delivery_info.get("deliveryFeeType", "")
    free_ship = fee_type == "FREE"
    shipping_fee = delivery_info.get("baseFee", 0) or 0

    stock_qty = _clamp_stock(d.get("stockQuantity", 0))
    is_sold_out = (d.get("productStatusType", "") != "SALE") or (
        stock_qty <= 0 and not options_list
    )

    source_url = (
        f"{BASE_URL}/{store_name}/products/{d.get('id', product_id)}"
        if store_name
        else ""
    )

    return {
        "site_product_id": str(d.get("id", product_id)),
        "siteProductId": str(d.get("id", product_id)),
        "name": name,
        "brand": brand,
        "manufacturer": manufacturer,
        "model_number": model_number,
        "original_price": sale_price,
        "originalPrice": sale_price,
        "sale_price": disc_price,
        "salePrice": disc_price,
        "discount_rate": disc_rate,
        "stock_quantity": stock_qty,
        "stockQuantity": stock_qty,
        "isSoldOut": is_sold_out,
        "is_sold_out": is_sold_out,
        "thumbnail_image_url": thumbnail,
        "thumbnailImageUrl": thumbnail,
        "images": images,
        "detail_images": detail_imgs,
        "detail_html": detail_html,
        "category": cat_str,
        "category1": cat1,
        "category2": cat2,
        "category3": cat3,
        "category4": cat4,
        "origin": origin,
        "material": material,
        "color": color,
        "sex": sex,
        "season": season,
        "options": options_list,
        "optionCombinations": options_list,
        "free_shipping": free_ship,
        "shipping_fee": shipping_fee,
        "source_url": source_url,
    }
