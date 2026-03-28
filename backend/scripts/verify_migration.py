"""DB 이전 후 데이터 무결성 검증 스크립트.

사용법:
  cd backend
  .venv/Scripts/python.exe scripts/verify_migration.py

.env의 DB 접속정보로 연결하여 검증합니다.
"""
import asyncio
import ssl
from backend.core.config import BackendSettings
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text


async def verify():
  settings = BackendSettings()
  ssl_ctx = ssl.create_default_context()
  ssl_ctx.check_hostname = False
  ssl_ctx.verify_mode = ssl.CERT_NONE
  url = (
    f"postgresql+asyncpg://{settings.read_db_user}:{settings.read_db_password}"
    f"@{settings.read_db_host}:{settings.read_db_port}/{settings.read_db_name}"
  )
  connect_args = {"ssl": ssl_ctx} if settings.use_db_ssl else {}
  engine = create_async_engine(url, connect_args=connect_args)

  checks_passed = 0
  checks_failed = 0

  async with engine.begin() as conn:
    print("=" * 60)
    print(" DB 이전 무결성 검증")
    print("=" * 60)

    # 1. 테이블별 행 수
    print("\n[1] 테이블별 행 수")
    tables = [
      "samba_policy", "samba_search_filter", "samba_collected_product",
      "samba_order", "samba_market_account", "samba_category_mapping",
      "samba_detail_template", "samba_name_rule", "samba_cs_inquiry",
      "samba_return", "samba_user",
    ]
    for tbl in tables:
      try:
        r = await conn.execute(text(f"SELECT COUNT(*) FROM {tbl}"))
        cnt = r.scalar()
        print(f"  {tbl:40s} {cnt:>8,}행")
      except Exception as e:
        print(f"  {tbl:40s} ERROR: {e}")

    # 2. 정책 적용 검증
    print("\n[2] 정책 적용 상태")
    r = await conn.execute(text(
      "SELECT COUNT(*) total, COUNT(applied_policy_id) with_policy "
      "FROM samba_search_filter"
    ))
    row = r.fetchone()
    total, with_policy = row[0], row[1]
    print(f"  검색필터 총 {total}개, 정책 적용 {with_policy}개")
    if with_policy == 0 and total > 0:
      print("  ⚠️ 경고: 정책이 하나도 적용되지 않았습니다!")
      checks_failed += 1
    else:
      checks_passed += 1

    # 3. 정책 ID 유효성 (고아 참조 확인)
    print("\n[3] 정책 참조 유효성")
    r = await conn.execute(text(
      "SELECT sf.id, sf.applied_policy_id "
      "FROM samba_search_filter sf "
      "WHERE sf.applied_policy_id IS NOT NULL "
      "AND sf.applied_policy_id NOT IN (SELECT id FROM samba_policy)"
    ))
    orphans = r.fetchall()
    if orphans:
      print(f"  ⚠️ 존재하지 않는 정책을 참조하는 필터 {len(orphans)}개:")
      for o in orphans:
        print(f"    filter={o[0]} → policy={o[1]} (존재하지 않음)")
      checks_failed += 1
    else:
      print("  ✓ 모든 정책 참조 유효")
      checks_passed += 1

    # 4. 인코딩 검증 (한글 이름 확인)
    print("\n[4] 인코딩 검증 (한글)")
    r = await conn.execute(text(
      "SELECT name FROM samba_search_filter "
      "WHERE name ~ '[가-힣]' LIMIT 5"
    ))
    korean_names = r.fetchall()
    if korean_names:
      print(f"  ✓ 한글 이름 정상 ({len(korean_names)}개 샘플 확인)")
      checks_passed += 1
    else:
      print("  ⚠️ 한글 이름을 찾을 수 없습니다 (인코딩 문제 가능)")
      checks_failed += 1

    # 5. 상품-필터 연결 확인
    print("\n[5] 상품-필터 연결")
    r = await conn.execute(text(
      "SELECT COUNT(*) total, "
      "COUNT(search_filter_id) with_filter, "
      "COUNT(source_url) with_url "
      "FROM samba_collected_product"
    ))
    row = r.fetchone()
    print(f"  상품 총 {row[0]}개, 필터 연결 {row[1]}개, source_url {row[2]}개")
    checks_passed += 1

    # 6. 컬럼 존재 확인 (최신 마이그레이션)
    print("\n[6] 최신 컬럼 존재 확인")
    expected_cols = {
      "samba_collected_product": ["source_url", "extra_data"],
      "samba_search_filter": ["tenant_id", "applied_policy_id", "parent_id", "is_folder"],
      "samba_policy": ["tenant_id", "extras"],
    }
    for tbl, cols in expected_cols.items():
      r = await conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        f"WHERE table_name = '{tbl}'"
      ))
      existing = {row[0] for row in r.fetchall()}
      for col in cols:
        if col in existing:
          print(f"  ✓ {tbl}.{col}")
          checks_passed += 1
        else:
          print(f"  ✗ {tbl}.{col} 누락!")
          checks_failed += 1

    # 결과 요약
    print("\n" + "=" * 60)
    print(f" 검증 결과: {checks_passed} 통과, {checks_failed} 실패")
    if checks_failed == 0:
      print(" ✓ 이전 성공!")
    else:
      print(" ⚠️ 문제가 발견되었습니다. 위 내용을 확인하세요.")
    print("=" * 60)


if __name__ == "__main__":
  asyncio.run(verify())
