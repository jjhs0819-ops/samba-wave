"""1377156 DB 모든 필드 채워졌는지 검증."""

import asyncio
from sqlalchemy import select
from backend.db.orm import get_read_session
from backend.domain.samba.collector.model import SambaCollectedProduct as CP


async def main() -> None:
    async with get_read_session() as session:
        row = (
            await session.execute(
                select(CP).where(
                    CP.source_site == "MUSINSA", CP.site_product_id == "1377156"
                )
            )
        ).scalar_one_or_none()
        if not row:
            print("❌ 상품 없음")
            return
        fields = [
            "id",
            "name",
            "brand",
            "manufacturer",
            "origin",
            "material",
            "color",
            "sex",
            "season",
            "style_code",
            "care_instructions",
            "quality_guarantee",
            "category",
            "category1",
            "category2",
            "category3",
            "source_url",
            "similar_no",
            "sale_price",
            "original_price",
            "cost",
            "free_shipping",
            "same_day_delivery",
            "sale_status",
            "status",
        ]
        print(f"=== {row.id} 필드 점검 ===")
        empty_count = 0
        for f in fields:
            v = getattr(row, f, None)
            mark = "✅" if (v not in (None, "", 0, False)) else "⚠️"
            if mark == "⚠️":
                empty_count += 1
            print(f"  {mark} {f}: {v!r}"[:120])
        print(
            f"  ✅ options: {len(row.options or [])}건 / addon_options: {len(row.addon_options or [])}건 / option_group_names: {row.option_group_names}"
        )
        print(f"\n[종합] 빈/0/false 필드 {empty_count}개")


if __name__ == "__main__":
    asyncio.run(main())
