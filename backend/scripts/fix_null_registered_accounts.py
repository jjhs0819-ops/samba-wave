"""registered_accounts 배열 내 null 값 제거."""

import asyncio
import json
import sys

sys.path.insert(0, "/app/backend")


async def main() -> None:
    import asyncpg

    from backend.core.config import settings

    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        ssl=False,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
    )

    # null 포함 상품 조회
    rows = await conn.fetch(
        """
        SELECT id, registered_accounts
        FROM samba_collected_product
        WHERE registered_accounts IS NOT NULL
          AND registered_accounts::text NOT IN ('[]', 'null', '')
          AND jsonb_typeof(registered_accounts::jsonb) = 'array'
          AND registered_accounts::jsonb @> 'null'
        """
    )

    print(f"null 포함 상품: {len(rows)}건")
    for r in rows:
        accs = json.loads(r["registered_accounts"])
        cleaned = [a for a in accs if a is not None]
        print(f"  {r['id']} | 전:{accs} → 후:{cleaned}")

    if not rows:
        print("없음.")
        await conn.close()
        return

    confirm = input("\nnull 제거 실행? (y/n): ").strip().lower()
    if confirm != "y":
        print("취소.")
        await conn.close()
        return

    fixed = 0
    for r in rows:
        accs = json.loads(r["registered_accounts"])
        cleaned = [a for a in accs if a is not None]
        await conn.execute(
            "UPDATE samba_collected_product SET registered_accounts = $1::json WHERE id = $2",
            json.dumps(cleaned),
            r["id"],
        )
        fixed += 1

    print(f"\n✓ {fixed}건 수정 완료")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
