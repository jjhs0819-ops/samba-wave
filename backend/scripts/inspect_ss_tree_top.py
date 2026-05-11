"""스마트스토어 트리 cat1 전체 + 생활/건강 하위 확인."""

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
        row = await conn.fetchrow(
            "SELECT cat1, cat2, cat3, cat4 FROM samba_category_tree WHERE site_name='smartstore'"
        )
        if not row:
            print("스마트스토어 트리 없음")
            return
        cat1 = row["cat1"]
        if isinstance(cat1, str):
            cat1 = json.loads(cat1)
        cat2 = row["cat2"]
        if isinstance(cat2, str):
            cat2 = json.loads(cat2)
        cat3 = row["cat3"]
        if isinstance(cat3, str):
            cat3 = json.loads(cat3)
        cat4 = row["cat4"]
        if isinstance(cat4, str):
            cat4 = json.loads(cat4)

        print(f"=== cat1 (전체 {len(cat1 or [])}개) ===")
        for c in cat1 or []:
            print(f"  - {c}")

        print("\n=== cat2['생활/건강'] ===")
        v = (cat2 or {}).get("생활/건강")
        print(json.dumps(v, ensure_ascii=False, indent=2))

        print("\n=== cat3['반려동물'] (cat2 안에 있다면) ===")
        v = (cat3 or {}).get("반려동물")
        print(json.dumps(v, ensure_ascii=False, indent=2))

        # '반려동물'이 들어간 모든 키
        print("\n=== '반려동물' 들어간 cat2/cat3/cat4 키 ===")
        for src_name, src in [("cat2", cat2), ("cat3", cat3), ("cat4", cat4)]:
            if not src:
                continue
            keys = [k for k in src.keys() if "반려" in k]
            if keys:
                print(f"  {src_name}: {keys}")

        # 매핑 후보 추출 시 사용되는 leaf 후보에 반려동물 포함 여부
        print(
            "\n=== leaf 후보 (cat2/cat3/cat4에서 추출한 전체 경로 중 '반려' 포함) ==="
        )
        leaves = []
        for c1 in cat1 or []:
            for c2 in (cat2 or {}).get(c1, []) or []:
                children3 = (cat3 or {}).get(c2)
                if not children3:
                    leaves.append(f"{c1} > {c2}")
                    continue
                for c3 in children3:
                    children4 = (cat4 or {}).get(c3)
                    if not children4:
                        leaves.append(f"{c1} > {c2} > {c3}")
                        continue
                    for c4 in children4:
                        leaves.append(f"{c1} > {c2} > {c3} > {c4}")
        pet_leaves = [path for path in leaves if "반려" in path or "강아지" in path]
        print(f"전체 leaf={len(leaves)}, '반려/강아지' leaf={len(pet_leaves)}")
        for p in pet_leaves[:30]:
            print(f"  {p}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
