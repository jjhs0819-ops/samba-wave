"""로컬 DB → Railway DB 데이터 동기화 스크립트 (COPY 기반 고속 전송)."""
import asyncio
import io
import asyncpg

LOCAL = "postgresql://test_user:test_password@localhost:5433/test_little_boy"
REMOTE = "postgresql://postgres:FNcJPEIJzIgpGhYAcpGixXWITQIjpFQU@centerbeam.proxy.rlwy.net:38057/railway"

TABLES = [
  "samba_settings",
  "samba_search_filter",
  "samba_collected_product",
  "samba_policy",
  "samba_name_rule",
  "samba_market_account",
  "samba_category_mapping",
  "samba_forbidden_word",
  "samba_shipment",
  "samba_order",
  "samba_monitor_event",
  "samba_user",
]


async def sync():
  local = await asyncpg.connect(LOCAL)
  remote = await asyncpg.connect(REMOTE)

  # Railway에 있는 컬럼만 사용 (로컬에만 있는 컬럼 무시)
  for table in TABLES:
    try:
      count = await local.fetchval(f"SELECT count(*) FROM {table}")
      if count == 0:
        print(f"{table}: 0건 스킵")
        continue

      # 양쪽 컬럼 교집합 구하기
      local_cols = await local.fetch(
        "SELECT column_name FROM information_schema.columns "
        f"WHERE table_name='{table}' ORDER BY ordinal_position"
      )
      remote_cols = await remote.fetch(
        "SELECT column_name FROM information_schema.columns "
        f"WHERE table_name='{table}' ORDER BY ordinal_position"
      )
      local_set = {r['column_name'] for r in local_cols}
      remote_set = {r['column_name'] for r in remote_cols}
      common = [r['column_name'] for r in local_cols if r['column_name'] in remote_set]

      if not common:
        print(f"{table}: 공통 컬럼 없음, 스킵")
        continue

      col_str = ", ".join(common)

      # Railway 기존 데이터 삭제
      await remote.execute(f"DELETE FROM {table}")

      # COPY OUT (로컬) → 메모리 → COPY IN (Railway)
      buf = io.BytesIO()
      await local.copy_from_query(
        f"SELECT {col_str} FROM {table}",
        output=buf,
        format="binary",
      )
      buf.seek(0)

      await remote.copy_to_table(
        table,
        source=buf,
        columns=common,
        format="binary",
      )

      remote_count = await remote.fetchval(f"SELECT count(*) FROM {table}")
      print(f"{table}: {count}건 → {remote_count}건 복사완료")

    except Exception as e:
      print(f"{table}: 에러 - {str(e)[:200]}")

  await local.close()
  await remote.close()
  print("\n동기화 완료!")

if __name__ == "__main__":
  asyncio.run(sync())
