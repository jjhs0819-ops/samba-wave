"""상품 그룹핑 유틸. D방식: similarNo → styleCode 모델코드 → 상품명 패턴."""

from __future__ import annotations

from collections import defaultdict
from typing import Optional


def parse_color_from_name(name: str) -> str:
    """상품명에서 색상 추출.
    패턴: '모델명 - 색상 / 스타일코드' → '색상' 반환.
    예: '에어 포스 1 07 M - 화이트 / CW2288-111' → '화이트'
    """
    if " - " not in name:
        return ""
    after_dash = name.split(" - ", 1)[1]
    if " / " in after_dash:
        return after_dash.split(" / ", 1)[0].strip()
    return after_dash.strip()


def extract_model_code(style_code: str) -> Optional[str]:
    """스타일코드에서 모델코드 추출.
    'CW2288-111' → 'CW2288', 'DD8959-001' → 'DD8959'.
    """
    if not style_code or "-" not in style_code:
        return None
    model_code = style_code.rsplit("-", 1)[0].strip()
    return model_code if model_code else None


def extract_model_name(name: str) -> Optional[str]:
    """상품명에서 모델명 추출.
    '에어 포스 1 07 M - 화이트 / CW2288-111' → '에어 포스 1 07 M'.
    """
    if " - " not in name:
        return None
    model_name = name.split(" - ", 1)[0].strip()
    return model_name if model_name else None


def generate_group_key(
    brand: str,
    similar_no: str | None,
    style_code: str | None,
    name: str | None,
) -> Optional[str]:
    """D방식 그룹핑 키 생성.

    우선순위:
    1. similarNo가 0이 아닌 경우 → 'similar_{similarNo}'
    2. style_code에서 모델코드 추출 → 'style_{brand}_{modelCode}'
    3. 상품명에서 ' - ' 앞 모델명 → 'name_{brand}_{modelName}'
    """
    brand_key = (brand or "").lower().replace(" ", "_")

    # 1순위: similarNo
    if similar_no and similar_no != "0":
        return f"similar_{similar_no}"

    # 2순위: style_code 모델코드 (하이픈 구분)
    model_code = extract_model_code(style_code or "")
    if model_code and brand_key:
        return f"style_{brand_key}_{model_code}"

    # 2-1순위: style_code 자체 (하이픈 없는 경우 — 블랙야크 등)
    sc = (style_code or "").strip()
    if sc and brand_key:
        return f"style_{brand_key}_{sc}"

    # 3순위: 상품명 패턴
    model_name = extract_model_name(name or "")
    if model_name and brand_key:
        return f"name_{brand_key}_{model_name}"

    return None


def group_products_by_key(products: list[dict]) -> dict[str, list[dict] | list]:
    """상품 리스트를 group_key별로 그룹핑.
    group_key가 없거나 1건뿐인 경우 singles로 분류.
    반환: { "groups": { key: [products] }, "singles": [products] }
    """
    key_map: dict[str, list[dict]] = defaultdict(list)
    no_key: list[dict] = []

    for p in products:
        gk = p.get("group_key")
        if gk:
            key_map[gk].append(p)
        else:
            no_key.append(p)

    groups: dict[str, list[dict]] = {}
    singles: list[dict] = list(no_key)
    for key, items in key_map.items():
        if len(items) >= 2:
            groups[key] = items
        else:
            singles.extend(items)

    return {"groups": groups, "singles": singles}
