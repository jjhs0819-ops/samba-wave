import asyncio
import asyncpg


# 애플리케이션에서 필요한 테이블 목록
REQUIRED_TABLES = [
    "samba_category_mapping",
    "samba_collected_product",
    "samba_policy",
    "samba_order",
    "samba_account",
    "samba_user",
    "samba_jobs",
    "samba_cs_inquiry",
    "samba_return",
    "samba_wholesale_product",
    "samba_sourcing_account",
    "samba_monitor_event",
]


async def check_tables():
    conn = await asyncpg.connect(
        host="34.64.205.34",
        port=5432,
        user="samba-user",
        password="SambaWave2024x",
        database="samba-wave",
    )

    rows = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
    )
    existing = {row["tablename"] for row in rows}

    print("=== 존재하는 테이블 ===")
    for t in sorted(existing):
        print(f"  ✓ {t}")

    print("\n=== 누락된 테이블 ===")
    missing = [t for t in REQUIRED_TABLES if t not in existing]
    if missing:
        for t in missing:
            print(f"  ✗ {t}")
    else:
        print("  없음 (모두 존재)")

    await conn.close()


asyncio.run(check_tables())
