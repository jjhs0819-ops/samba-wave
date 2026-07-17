"""더현대Hi 오토튠 진단 스크립트.

수동으로 1상품 refresh 사이클 돌려 RefreshResult 전 필드를 출력. 사이트 화면
값과 사람이 직접 대조해 정합성 확인.

사용:
    ENABLE_THEHYUNDAI=1 python scripts/diag_thehyundai_autotune.py 40B0696270
    ENABLE_THEHYUNDAI=1 python scripts/diag_thehyundai_autotune.py https://hi.thehyundai.com/product/40B0696270

검증 포인트:
  - new_sale_price : 사이트 메인 빨간 가격 일치
  - new_original_price : 취소선 정가 일치
  - new_cost : 사이트 "최대혜택가" 박스 숫자 일치 (현대백화점카드 즉시할인 반영)
  - new_options : 옵션별 재고/품절 일치
  - new_sale_status : ostkYn 기반
  - price_uncertain : maxBnftList 호출 실패 시 True
  - deleted_from_source : detail 404 시 True
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main() -> int:
    parser = argparse.ArgumentParser(description="더현대Hi refresh 진단")
    parser.add_argument(
        "slitm_cd",
        help="상품 slitmCd (예: 40B0696270) 또는 상품 URL",
    )
    parser.add_argument(
        "--also-detail",
        action="store_true",
        help="get_detail() 도 함께 호출하여 결과 출력",
    )
    args = parser.parse_args()

    if os.getenv("ENABLE_THEHYUNDAI") != "1":
        print(
            "[WARN] ENABLE_THEHYUNDAI=1 미설정 — 플러그인 비활성. "
            "환경변수 설정 후 재실행.",
            file=sys.stderr,
        )
        return 2

    # plugin 등록 확인
    from backend.domain.samba.plugins import SOURCING_PLUGINS

    plugin = SOURCING_PLUGINS.get("THEHYUNDAI")
    if not plugin:
        print("[FAIL] SOURCING_PLUGINS['THEHYUNDAI'] 미등록", file=sys.stderr)
        return 1

    print(
        f"[OK] plugin loaded: site_name={plugin.site_name} "
        f"concurrency={plugin.concurrency} request_interval={plugin.request_interval}"
    )

    from backend.domain.samba.proxy.thehyundai_sourcing import (
        TheHyundaiSourcingClient,
    )

    client = TheHyundaiSourcingClient()
    slitm_cd = TheHyundaiSourcingClient._extract_slitm_cd(args.slitm_cd)
    if not slitm_cd:
        print(f"[FAIL] slitmCd 추출 불가: {args.slitm_cd!r}", file=sys.stderr)
        return 1

    print(f"[INFO] target slitmCd = {slitm_cd}\n")

    if args.also_detail:
        print("=" * 60)
        print(" get_detail() 결과")
        print("=" * 60)
        detail = await client.get_product_detail(slitm_cd)
        if not detail:
            print("[FAIL] 상세 응답 없음 (404 or result!=SUCCESS)")
        else:
            display = {
                k: v
                for k, v in detail.items()
                if k != "descriptionHtml"  # HTML 너무 길어서 제외
            }
            display["descriptionHtml_len"] = len(detail.get("descriptionHtml") or "")
            print(json.dumps(display, ensure_ascii=False, indent=2))
        print()

    # 모의 product 객체 (RefreshResult 가 product 의 attr 만 읽음)
    fake_product = SimpleNamespace(
        id=f"cp_test_{slitm_cd}",
        site_product_id=slitm_cd,
        siteProductId=slitm_cd,
        source_url=f"https://hi.thehyundai.com/product/{slitm_cd}",
        sourceUrl="",
        options=[],
        sale_price=0,
        sale_status="in_stock",
        source_site="THEHYUNDAI",
    )

    print("=" * 60)
    print(" refresh() 결과")
    print("=" * 60)
    result = await client.refresh_product(fake_product)

    output = {
        "product_id": result.product_id,
        "new_sale_price": result.new_sale_price,
        "new_original_price": result.new_original_price,
        "new_cost": result.new_cost,
        "new_cost_excl_held_point": result.new_cost_excl_held_point,
        "new_sale_status": result.new_sale_status,
        "new_options": result.new_options,
        "changed": result.changed,
        "stock_changed": result.stock_changed,
        "deleted_from_source": result.deleted_from_source,
        "price_uncertain": result.price_uncertain,
        "error": result.error,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    print()

    # 사람 검증용 요약
    print("=" * 60)
    print(" 사람 검증 항목 (사이트 화면과 대조)")
    print("=" * 60)
    print(f"  사이트 URL    : https://hi.thehyundai.com/product/{slitm_cd}")
    print(f"  정가          : {result.new_original_price:,.0f}원" if result.new_original_price else "  정가          : N/A")
    print(f"  판매가        : {result.new_sale_price:,.0f}원" if result.new_sale_price else "  판매가        : N/A")
    print(
        f"  최대혜택가    : {result.new_cost:,.0f}원"
        if result.new_cost
        else "  최대혜택가    : N/A"
    )
    print(f"  품절          : {'예' if result.new_sale_status == 'sold_out' else '아니오'}")
    if result.new_options:
        print(f"  옵션 {len(result.new_options)}개:")
        for opt in result.new_options[:10]:
            sold = "(품절)" if opt.get("isSoldOut") else f"(재고 {opt.get('stock', 0)})"
            print(f"    - {opt.get('name')} : {opt.get('price', 0):,}원 {sold}")
        if len(result.new_options) > 10:
            print(f"    ... 외 {len(result.new_options) - 10}건")
    if result.price_uncertain:
        print("  ⚠ price_uncertain=True (maxBnftList 호출 실패)")
    if result.deleted_from_source:
        print("  ⚠ deleted_from_source=True (사이트에서 삭제됨)")
    if result.error:
        print(f"  ⚠ error: {result.error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
