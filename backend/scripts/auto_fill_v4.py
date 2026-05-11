"""v4 자동 채움."""

import asyncio
import asyncpg
import json
from collections import defaultdict
from backend.core.config import settings


async def main():
    with open("/tmp/empty_v4.json", "r", encoding="utf-8") as f:
        data = json.load(f)
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
        rows_u, keys_a = 0, 0
        per_market = defaultdict(int)
        async with conn.transaction():
            for entry in data:
                rec = await conn.fetchrow(
                    "SELECT target_mappings FROM samba_category_mapping WHERE id=$1",
                    entry["id"],
                )
                if not rec:
                    continue
                tm = rec["target_mappings"]
                if isinstance(tm, str):
                    tm = json.loads(tm)
                if not isinstance(tm, dict):
                    tm = {}
                merged = dict(tm)
                added = 0
                for mk, cands in entry["candidates"].items():
                    if isinstance(merged.get(mk), str) and merged.get(mk).strip():
                        continue
                    if not cands:
                        continue
                    chosen = cands[0]
                    if chosen not in mv.get(mk, set()):
                        continue
                    merged[mk] = chosen
                    added += 1
                    per_market[mk] += 1
                if added:
                    await conn.execute(
                        "UPDATE samba_category_mapping SET target_mappings=$1::jsonb, updated_at=NOW() WHERE id=$2",
                        json.dumps(merged, ensure_ascii=False),
                        entry["id"],
                    )
                    rows_u += 1
                    keys_a += added
        print(f"v4: 행 {rows_u}, 키 {keys_a}")
        for m in sorted(per_market.keys()):
            print(f"  {m}: {per_market[m]}")
    finally:
        await conn.close()


asyncio.run(main())
