"""반려동물 강아지의류 카테고리 매핑 현황 조회."""

import asyncio
import asyncpg
import json
from backend.core.config import settings


async def main() -> None:
    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        # 1) source_category에 강아지의류 들어간 매핑 전부
        rows = await conn.fetch(
            """
            SELECT id, tenant_id, source_site, source_category, target_mappings
            FROM samba_category_mapping
            WHERE source_category ILIKE '%강아지의류%'
               OR source_category ILIKE '%반려동물%'
            ORDER BY source_site, source_category
            """
        )
        print(f"=== 매핑 {len(rows)}건 ===")
        for r in rows:
            tm = r["target_mappings"]
            if isinstance(tm, str):
                try:
                    tm = json.loads(tm)
                except Exception:
                    pass
            print(
                f"\n[{r['source_site']}] {r['source_category']}"
                f"\n  id={r['id']} tenant={r['tenant_id']}"
                f"\n  target_mappings={json.dumps(tm, ensure_ascii=False, indent=2)}"
            )

        # 2) 스마트스토어 트리에서 반려동물/강아지의류 하위 leaf 후보
        print("\n\n=== 스마트스토어 트리: 반려동물 ===")
        ss = await conn.fetchrow(
            "SELECT cat1, cat2, cat3, cat4 FROM samba_category_tree WHERE site_name='smartstore'"
        )
        if ss:
            cat1 = ss["cat1"]
            if isinstance(cat1, str):
                cat1 = json.loads(cat1)
            print(f"cat1에 '반려동물' 존재? {'반려동물' in (cat1 or [])}")
            cat2 = ss["cat2"]
            if isinstance(cat2, str):
                cat2 = json.loads(cat2)
            cat3 = ss["cat3"]
            if isinstance(cat3, str):
                cat3 = json.loads(cat3)
            cat4 = ss["cat4"]
            if isinstance(cat4, str):
                cat4 = json.loads(cat4)
            print(
                f"cat2['반려동물']={json.dumps(cat2.get('반려동물') if cat2 else None, ensure_ascii=False)}"
            )
            print(
                f"cat3['반려동물의류']={json.dumps(cat3.get('반려동물의류') if cat3 else None, ensure_ascii=False)}"
            )
            print(
                f"cat4['강아지의류']={json.dumps(cat4.get('강아지의류') if cat4 else None, ensure_ascii=False)}"
            )

        # 3) 롯데ON 트리
        print("\n\n=== 롯데ON 트리: 반려동물 ===")
        lo = await conn.fetchrow(
            "SELECT cat1, cat2, cat3, cat4 FROM samba_category_tree WHERE site_name='lotteon'"
        )
        if lo:
            cat1 = lo["cat1"]
            if isinstance(cat1, str):
                cat1 = json.loads(cat1)
            print(f"cat1에 '반려동물' 존재? {'반려동물' in (cat1 or [])}")
            cat2 = lo["cat2"]
            if isinstance(cat2, str):
                cat2 = json.loads(cat2)
            cat3 = lo["cat3"]
            if isinstance(cat3, str):
                cat3 = json.loads(cat3)
            cat4 = lo["cat4"]
            if isinstance(cat4, str):
                cat4 = json.loads(cat4)
            print(
                f"cat2['반려동물']={json.dumps(cat2.get('반려동물') if cat2 else None, ensure_ascii=False)}"
            )
            print(
                f"cat3['반려동물의류']={json.dumps(cat3.get('반려동물의류') if cat3 else None, ensure_ascii=False)}"
            )
            print(
                f"cat4['강아지의류']={json.dumps(cat4.get('강아지의류') if cat4 else None, ensure_ascii=False)}"
            )
        else:
            print("(롯데ON 트리 없음)")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
