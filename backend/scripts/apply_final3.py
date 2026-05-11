"""인센스 최종."""

import asyncio
import asyncpg
import json
from backend.core.config import settings

D = {
    "cm_01KQW2DYRSQK0BX3BA99HFJ99R": {
        "auction": "조명/인테리어 > 아로마/캔들용품 > 초/향초",
        "gmarket": "조명/인테리어 > 아로마/캔들용품 > 초/향초",
        "smartstore": "가구/인테리어 > 인테리어소품 > 아로마/캔들용품 > 초/향초",
    },
}


async def main():
    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        tree_rows = await conn.fetch(
            "SELECT site_name, cat1, cat2 FROM samba_category_tree"
        )
        mv = {}
        for r in tree_rows:
            c1, c2 = r["cat1"], r["cat2"]
            if isinstance(c1, str):
                c1 = json.loads(c1)
            if isinstance(c2, str):
                c2 = json.loads(c2)
            p = set()
            if isinstance(c1, list):
                p.update(x for x in c1 if isinstance(x, str))
            if isinstance(c2, dict):
                p.update(k for k in c2.keys() if isinstance(k, str))
            elif isinstance(c2, list):
                p.update(x for x in c2 if isinstance(x, str))
            mv[r["site_name"]] = p
        rows_u, keys_a, rej = 0, 0, []
        async with conn.transaction():
            for mid, add in D.items():
                rec = await conn.fetchrow(
                    "SELECT target_mappings FROM samba_category_mapping WHERE id=$1",
                    mid,
                )
                if not rec:
                    continue
                tm = rec["target_mappings"]
                if isinstance(tm, str):
                    tm = json.loads(tm)
                if not isinstance(tm, dict):
                    tm = {}
                merged = dict(tm)
                n = 0
                for mk, path in add.items():
                    if isinstance(merged.get(mk), str) and merged[mk].strip():
                        continue
                    if path not in mv.get(mk, set()):
                        rej.append(f"{mid} {mk}: {path}")
                        continue
                    merged[mk] = path
                    n += 1
                if n:
                    await conn.execute(
                        "UPDATE samba_category_mapping SET target_mappings=$1::jsonb, updated_at=NOW() WHERE id=$2",
                        json.dumps(merged, ensure_ascii=False),
                        mid,
                    )
                    rows_u += 1
                    keys_a += n
        print(f"final3: 행 {rows_u}, 키 {keys_a}, 미일치 {len(rej)}")
        for r in rej:
            print(f"  {r}")
    finally:
        await conn.close()


asyncio.run(main())
