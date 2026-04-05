"""requested_count 복구 스크립트.

버그로 인해 requested_count = existing_count 로 덮어씌워진 필터들을
existing_count + 100 으로 복구한다.

사용법:
    cd backend
    python scripts/fix_requested_count.py
"""

import asyncio
import asyncpg


LOCAL = dict(
    host="localhost",
    port=5432,
    user="hosoo_kim",
    password="123456",
    database="hosoo_samba",
)


async def fix():
    conn = await asyncpg.connect(**LOCAL)
    try:
        # 현재 상태 확인
        rows = await conn.fetch(
            """
            SELECT
                sf.id,
                sf.name,
                sf.source_site,
                sf.requested_count,
                COUNT(cp.id) AS existing_count
            FROM samba_search_filter sf
            LEFT JOIN samba_collected_product cp ON cp.search_filter_id = sf.id
            WHERE sf.is_folder = false
            GROUP BY sf.id, sf.name, sf.source_site, sf.requested_count
            HAVING COUNT(cp.id) >= sf.requested_count AND COUNT(cp.id) > 0
            ORDER BY sf.source_site, sf.name
            """
        )

        if not rows:
            print("복구가 필요한 필터 없음.")
            return

        print(f"복구 대상 필터: {len(rows)}개\n")
        print(
            f"{'필터명':<50} {'소싱처':<12} {'현재요청수':>10} {'수집수':>8} {'변경후':>10}"
        )
        print("-" * 95)

        update_ids = []
        for r in rows:
            new_count = r["existing_count"] + 100
            print(
                f"{r['name']:<50} {r['source_site']:<12} "
                f"{r['requested_count']:>10} {r['existing_count']:>8} {new_count:>10}"
            )
            update_ids.append((r["id"], new_count))

        print()
        confirm = input("위 필터들의 requested_count를 복구하겠습니까? (y/n): ")
        if confirm.strip().lower() != "y":
            print("취소됨.")
            return

        for filter_id, new_count in update_ids:
            await conn.execute(
                "UPDATE samba_search_filter SET requested_count = $1 WHERE id = $2",
                new_count,
                filter_id,
            )

        print(f"\n완료: {len(update_ids)}개 필터 복구됨.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(fix())
