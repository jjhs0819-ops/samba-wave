"""name_en/name_ja 누락 SNKRDUNK 상품 전수 채우기.

DB에서 name_en IS NULL인 site_product_id 추출 →
SNKRDUNK API /v1/apparels/{sid} 호출 → name_en, name_ja DB 업데이트.
재개 가능(이미 채워진 건 skip).
"""

import asyncio
import io
import json
import sys
import urllib.request

import asyncpg

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

DB_URL = "postgresql://samba:09aac90f3fb8c4394ad2d6062b1a5910@127.0.0.1:5432/samba"
CONCURRENCY = 12
REPORT_EVERY = 100

JH = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "ja-JP,ja;q=0.9",
    "Referer": "https://snkrdunk.com/",
}


def jp_fetch(sid: str):
    """SNKRDUNK API에서 영문명/일문명 반환."""

    def get(u):
        return json.loads(
            urllib.request.urlopen(
                urllib.request.Request(u, headers=JH), timeout=10
            ).read()
        )

    d = get(f"https://snkrdunk.com/v1/apparels/{sid}")
    return (d.get("name") or "").strip(), (d.get("localizedName") or "").strip()


async def main():
    pool = await asyncpg.create_pool(DB_URL, ssl=False, min_size=2, max_size=4)

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, site_product_id
            FROM samba_collected_product
            WHERE source_site = 'SNKRDUNK'
              AND (name_en IS NULL OR name_en = '')
            ORDER BY id
        """)

    total = len(rows)
    print(f"대상: {total:,}건", flush=True)

    sem = asyncio.Semaphore(CONCURRENCY)
    cnt = {"ok": 0, "fail": 0, "empty": 0, "n": 0}

    async def one(cp_id, sid):
        try:
            name_en, name_ja = await asyncio.to_thread(jp_fetch, sid)
        except Exception:
            cnt["fail"] += 1
            return

        if not name_en:
            cnt["empty"] += 1
            return

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE samba_collected_product
                SET name_en = $1, name_ja = $2, updated_at = NOW()
                WHERE id = $3
            """,
                name_en,
                name_ja,
                cp_id,
            )
        cnt["ok"] += 1

    async def guarded(cp_id, sid):
        async with sem:
            await one(cp_id, sid)
            cnt["n"] += 1
            n = cnt["n"]
            if n % REPORT_EVERY == 0 or n == total:
                print(
                    f"[{n:,}/{total:,}] 수집={cnt['ok']:,} 없음={cnt['empty']:,} 실패={cnt['fail']:,}",
                    flush=True,
                )

    await asyncio.gather(*[guarded(str(r["id"]), r["site_product_id"]) for r in rows])
    await pool.close()
    print(
        f"\n완료: 수집={cnt['ok']:,} 없음={cnt['empty']:,} 실패={cnt['fail']:,} / 전체={total:,}"
    )


asyncio.run(main())
