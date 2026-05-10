"""1377156 단일 수집 — 이중 옵션 fix 검증.

새로 배포된 _fetch_options 카르테시안 곱 로직이 제대로 동작하는지 확인.
"""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from backend.db.orm import get_write_session
from backend.api.v1.routers.samba.collector_common import (
    get_musinsa_cookie,
    _get_services,
)
from backend.domain.samba.collector.model import (
    SambaCollectedProduct as CPModel,
    SambaSearchFilter as SFModel,
)
from backend.domain.samba.proxy.musinsa import MusinsaClient
from backend.domain.samba.collector.grouping import (
    generate_group_key,
    parse_color_from_name,
)


GOODS_NO = "1377156"
URL = f"https://www.musinsa.com/products/{GOODS_NO}"


async def main() -> None:
    async with get_write_session() as session:
        cookie = await get_musinsa_cookie(session)
        if not cookie:
            print("⚠️ 무신사 쿠키 없음 — 확장앱에서 먼저 로그인 필요")
            return

        client = MusinsaClient(cookie=cookie)
        data = await client.get_goods_detail(GOODS_NO)
        if not data or not data.get("name"):
            print("❌ 무신사 상품 조회 실패")
            return

        brand = (data.get("brand") or "unknown").strip()
        options = data.get("options") or []

        # 옵션 구조 분석
        print("\n=== 1377156 수집 결과 ===")
        print(f"  name: {data.get('name')}")
        print(f"  brand: {brand}")
        print(f"  salePrice: {data.get('salePrice')}")
        print(f"  options 개수: {len(options)}")

        # 메인-only vs 메인×엑스트라 조합 판별
        with_slash = sum(1 for o in options if " / " in (o.get("name") or ""))
        without_slash = len(options) - with_slash
        print(f"  옵션 분석: 단일 {without_slash}건 + 2-depth {with_slash}건")

        # 샘플 출력
        print("\n  옵션 샘플 10건:")
        for o in options[:10]:
            print(
                f"    {o.get('name'):<70} price={o.get('price')} stock={o.get('stock')}"
            )
        if len(options) > 10:
            print(f"    ... +{len(options) - 10}건")

        # SearchFilter upsert
        svc = _get_services(session)
        filter_name = f"MUSINSA_{brand}_{GOODS_NO}"
        existing_sf = (
            await session.execute(
                select(SFModel).where(
                    SFModel.source_site == "MUSINSA", SFModel.name == filter_name
                )
            )
        ).scalar_one_or_none()
        if existing_sf:
            sf = existing_sf
        else:
            sf = await svc.create_filter(
                {
                    "source_site": "MUSINSA",
                    "name": filter_name,
                    "keyword": URL,
                    "requested_count": 1,
                }
            )

        sale_status = data.get("saleStatus", "in_stock")
        similar_no = str(data.get("similarNo", "0"))
        initial_snapshot = {
            "date": datetime.now(timezone.utc).isoformat(),
            "sale_price": data.get("salePrice", 0),
            "original_price": data.get("originalPrice", 0),
            "options": options,
        }

        product_data = {
            "source_site": "MUSINSA",
            "site_product_id": GOODS_NO,
            "search_filter_id": sf.id,
            "name": data.get("name", ""),
            "brand": brand,
            "original_price": data.get("originalPrice", 0),
            "sale_price": data.get("salePrice", 0),
            "cost": data.get("bestBenefitPrice") or None,
            "images": data.get("images", []),
            "detail_images": data.get("detailImages") or [],
            "options": options,
            "category": data.get("category", ""),
            "category1": data.get("category1", ""),
            "category2": data.get("category2", ""),
            "category3": data.get("category3", ""),
            "category4": data.get("category4", ""),
            "manufacturer": data.get("manufacturer", ""),
            "origin": data.get("origin", ""),
            "material": data.get("material", ""),
            "color": data.get("color", "")
            or parse_color_from_name(data.get("name", "")),
            "similar_no": similar_no,
            "style_code": data.get("styleNo", ""),
            "group_key": generate_group_key(
                brand=brand,
                similar_no=similar_no,
                style_code=data.get("styleNo", ""),
                name=data.get("name", ""),
            ),
            "detail_html": data.get("detailHtml", "") or "",
            "status": "collected",
            "sale_status": sale_status,
            "free_shipping": data.get("freeShipping", False),
            "same_day_delivery": data.get("sameDayDelivery", False),
            "is_point_restricted": data.get("isPointRestricted"),
            "price_history": [initial_snapshot],
        }

        existing = (
            await session.execute(
                select(CPModel).where(
                    CPModel.source_site == "MUSINSA",
                    CPModel.site_product_id == GOODS_NO,
                )
            )
        ).scalar_one_or_none()

        if existing:
            collected = await svc.update_collected_product(existing.id, product_data)
            print(
                f"\n  ✏️ DB 업데이트: {collected.id if hasattr(collected, 'id') else existing.id}"
            )
        else:
            collected = await svc.create_collected_product(product_data)
            print(
                f"\n  ✨ DB 신규 생성: {collected.id if hasattr(collected, 'id') else '?'}"
            )

        sf.last_collected_at = datetime.now(timezone.utc)
        session.add(sf)
        await session.commit()
        print("[수집 완료]")


if __name__ == "__main__":
    asyncio.run(main())
