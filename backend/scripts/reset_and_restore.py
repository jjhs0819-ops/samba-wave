"""로컬 DB → Cloud SQL 데이터 이전 스크립트"""

import asyncio
import asyncpg

LOCAL = dict(
    host="localhost",
    port=5432,
    user="hosoo_kim",
    password="123456",
    database="hosoo_samba",
)
CLOUD = dict(
    host="34.64.205.34",
    port=5432,
    user="samba-user",
    password="SambaWave2024x",
    database="samba-wave",
)

# 이전할 테이블 목록 (순서 중요)
TABLES = [
    "samba_settings",
    "samba_search_filter",
    "samba_policy",
    "samba_market_account",
    "samba_category_mapping",
    "samba_category_tree",
    "samba_detail_template",
    "samba_name_rule",
    "samba_collected_product",
    "samba_shipment",
    "samba_order",
    "samba_return",
    "samba_cs_inquiry",
    "samba_wholesale_product",
    "samba_sourcing_account",
    "samba_forbidden_word",
    "samba_user",
]


async def get_columns(conn, table):
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=$1 ORDER BY ordinal_position",
        table,
    )
    return [r["column_name"] for r in rows]


async def migrate():
    print("로컬 DB 연결 중...")
    local = await asyncpg.connect(**LOCAL)
    print("Cloud SQL 연결 중...")
    cloud = await asyncpg.connect(**CLOUD)

    for table in TABLES:
        try:
            # Cloud SQL 테이블 비우기
            await cloud.execute(f'TRUNCATE TABLE "{table}" CASCADE')

            # 로컬에서 컬럼 목록 가져오기
            local_cols = await get_columns(local, table)
            cloud_cols = await get_columns(cloud, table)

            # 공통 컬럼만 사용
            cols = [c for c in local_cols if c in cloud_cols]
            if not cols:
                print(f"  ⚠ {table}: 공통 컬럼 없음, 건너뜀")
                continue

            col_str = ", ".join(f'"{c}"' for c in cols)

            # 로컬에서 데이터 가져오기
            rows = await local.fetch(f'SELECT {col_str} FROM "{table}"')
            if not rows:
                print(f"  ✓ {table}: 데이터 없음")
                continue

            # Cloud SQL에 삽입 (NULL → 기본값 처리)
            placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
            insert_sql = f'INSERT INTO "{table}" ({col_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'

            data = []
            for row in rows:
                values = []
                for col in cols:
                    val = row[col]
                    # sourcing_shipping_fee NULL 처리
                    if col == "sourcing_shipping_fee" and val is None:
                        val = 0.0
                    values.append(val)
                data.append(values)

            await cloud.executemany(insert_sql, data)
            print(f"  ✓ {table}: {len(rows)}건 이전 완료")

        except Exception as e:
            print(f"  ✗ {table}: 오류 - {e}")

    await local.close()
    await cloud.close()
    print("\n데이터 이전 완료!")


asyncio.run(migrate())
