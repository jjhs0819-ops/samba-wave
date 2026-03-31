"""쿠팡 등록 Dry-Run 테스트 스크립트.

실제 쿠팡 API 호출 없이 SambaCollectedProduct → 쿠팡 상품 데이터 변환을 검증한다.

실행:
  cd backend
  source .venv/bin/activate
  python -m scripts.test_coupang_dryrun
"""

import asyncio
import json
import sys
from pathlib import Path

# .env 로드
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from sqlmodel import select

from backend.db.orm import get_read_session
from backend.domain.samba.collector.model import SambaCollectedProduct
from backend.domain.samba.category.model import SambaCategoryTree
from backend.domain.samba.proxy.coupang import CoupangClient


async def main() -> None:
    # 1. DB에서 GSSHOP 상품 1개 조회
    async with get_read_session() as session:
        stmt = select(SambaCollectedProduct).where(
            SambaCollectedProduct.source_site == "GSShop"
        ).limit(1)
        result = await session.exec(stmt)
        product = result.first()

        # 쿠팡 카테고리 트리 조회
        cat_stmt = select(SambaCategoryTree).where(
            SambaCategoryTree.site_name == "coupang"
        )
        cat_result = await session.exec(cat_stmt)
        cat_tree = cat_result.first()

    if not product:
        print("GSSHOP 상품 없음 — 수집 후 다시 실행하세요.")
        sys.exit(0)

    print(f"=== 대상 상품 ===")
    print(f"  ID       : {product.id}")
    print(f"  상품명   : {product.name}")
    print(f"  소싱처   : {product.source_site}")
    print(f"  원가     : {product.original_price}")
    print(f"  판매가   : {product.sale_price}")
    print(f"  브랜드   : {product.brand}")
    print(f"  카테고리 : {product.category1} > {product.category2} > {product.category3}")
    print(f"  이미지수 : {len(product.images) if product.images else 0}")
    print(f"  옵션수   : {len(product.options) if product.options else 0}")
    print()

    # 2. cat2에서 경로 → 숫자 코드 변환 후 transform_product 호출
    cat2_map = cat_tree.cat2 if cat_tree and cat_tree.cat2 else {}
    category_code = str(cat2_map.get(product.category, 0)) if product.category else "0"
    print(f"  카테고리코드: {product.category} → {category_code}")

    product_dict = product.model_dump()
    transformed = CoupangClient.transform_product(product_dict, category_id=category_code)

    # 3. 변환 결과 JSON 출력
    print("=== 변환 결과 (JSON) ===")
    print(json.dumps(transformed, ensure_ascii=False, indent=2))
    print()

    # 4. 필수 필드 체크
    print("=== 필수 필드 체크 ===")
    errors: list[str] = []

    # 최상위 필수 필드
    top_required = ["displayCategoryCode", "sellerProductName", "brand", "deliveryMethod", "items"]
    for field in top_required:
        val = transformed.get(field)
        if val is None or val == "":
            errors.append(f"[최상위] '{field}' 누락 또는 빈 값")
        else:
            print(f"  OK  {field} = {repr(val)[:80]}")

    # items 검증
    items = transformed.get("items", [])
    if not items:
        errors.append("[items] 아이템이 0개입니다")
    else:
        print(f"  OK  items 개수 = {len(items)}")

    for i, item in enumerate(items):
        prefix = f"[items[{i}]]"

        # 아이템 필수 필드
        item_required = ["itemName", "originalPrice", "salePrice", "images", "notices", "contents"]
        for field in item_required:
            val = item.get(field)
            if val is None or val == "" or val == []:
                errors.append(f"{prefix} '{field}' 누락 또는 빈 값")
            else:
                display = repr(val)[:60] if not isinstance(val, list) else f"({len(val)}개)"
                print(f"  OK  {prefix} {field} = {display}")

        # 대표 이미지 존재 여부
        images = item.get("images", [])
        has_rep = any(img.get("imageType") == "REPRESENTATION" for img in images)
        if not has_rep:
            errors.append(f"{prefix} REPRESENTATION 이미지 없음")
        else:
            print(f"  OK  {prefix} REPRESENTATION 이미지 존재")

    # 5. 결과 리포트
    print()
    if errors:
        print(f"=== 경고: {len(errors)}건 누락 ===")
        for err in errors:
            print(f"  NG  {err}")
    else:
        print("=== 모든 필수 필드 정상 ===")


if __name__ == "__main__":
    asyncio.run(main())
