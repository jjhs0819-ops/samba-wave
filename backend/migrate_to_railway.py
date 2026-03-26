"""로컬 DB → Railway DB 마이그레이션 스크립트."""
import asyncio
import asyncpg

LOCAL = "postgresql://test_user:test_password@localhost:5433/test_little_boy"
RAILWAY = "postgresql://postgres:FNcJPEIJzIgpGhYAcpGixXWITQIjpFQU@centerbeam.proxy.rlwy.net:38057/railway"

TABLES = [
    "samba_user", "samba_settings", "samba_forbidden_word", "samba_market_account",
    "samba_policy", "samba_name_rule", "samba_detail_template", "samba_search_filter",
    "samba_collected_product", "samba_category_mapping", "samba_category_tree",
    "samba_order", "samba_return", "samba_cs_inquiry", "samba_shipment",
    "samba_contact_log", "samba_monitor_event",
]


async def get_columns(conn, table):
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name = $1 ORDER BY ordinal_position",
        table,
    )
    return [r["column_name"] for r in rows]


async def main():
    print("로컬 DB 연결...")
    local = await asyncpg.connect(LOCAL)
    print("Railway DB 연결...")
    railway = await asyncpg.connect(RAILWAY)

    await railway.execute("SET session_replication_role = replica;")

    # 모든 테이블 한번에 TRUNCATE
    print("Railway 기존 데이터 전체 삭제...")
    for table in reversed(TABLES):
        try:
            await railway.execute(f'TRUNCATE "{table}" CASCADE')
        except Exception:
            pass

    total = 0
    for table in TABLES:
        try:
            local_cols = set(await get_columns(local, table))
            railway_cols = set(await get_columns(railway, table))
            common_cols = sorted(local_cols & railway_cols)
            if not common_cols:
                print(f"  {table}: 공통 컬럼 없음 스킵")
                continue

            col_select = ", ".join(f'"{c}"' for c in common_cols)
            rows = await local.fetch(f'SELECT {col_select} FROM "{table}"')
            if not rows:
                print(f"  {table}: 0건 스킵")
                continue

            records = [tuple(row[c] for c in common_cols) for row in rows]
            await railway.copy_records_to_table(table, records=records, columns=common_cols)

            skipped = local_cols - railway_cols
            extra = f" (컬럼 {len(skipped)}개 스킵)" if skipped else ""
            print(f"  {table}: {len(records)}건 완료{extra}")
            total += len(records)
        except Exception as e:
            print(f"  {table}: 실패 - {str(e)[:120]}")

    await railway.execute("SET session_replication_role = DEFAULT;")
    await local.close()
    await railway.close()
    print(f"\n총 {total}건 마이그레이션 완료")


if __name__ == "__main__":
    asyncio.run(main())
