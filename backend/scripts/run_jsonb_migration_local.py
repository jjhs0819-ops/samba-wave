"""로컬 DB: tags/market_product_nos JSON→JSONB + GIN 인덱스 마이그레이션 (lock_timeout 우회)"""

import asyncio
import asyncpg


async def main():
    conn = await asyncpg.connect(
        host="localhost",
        port=5434,
        database="railway",
        user="postgres",
        password="gemini0674@@",
    )

    # 현재 alembic 버전 확인
    ver = await conn.fetchval("SELECT version_num FROM alembic_version LIMIT 1")
    print(f"현재 alembic 버전: {ver}")

    if ver == "zzzzz_tags_jsonb_gin":
        print("이미 마이그레이션 완료됨. 종료.")
        await conn.close()
        return

    if ver != "zzzz_search_gin_indexes":
        print(f"예상 버전(zzzz_search_gin_indexes)이 아님: {ver}")
        print("계속 진행합니다...")

    # lock_timeout 없이 실행
    await conn.execute("SET lock_timeout = 0")
    print("lock_timeout 해제 완료")

    # 1. tags 컬럼 JSON → JSONB
    print("1. tags 컬럼 타입 확인 중...")
    tags_type = await conn.fetchval(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'samba_collected_product' AND column_name = 'tags'"
    )
    print(f"   현재 tags 타입: {tags_type}")

    if tags_type == "json":
        print("   tags JSON → JSONB 변환 중... (시간이 걸릴 수 있음)")
        await conn.execute(
            "ALTER TABLE samba_collected_product ALTER COLUMN tags TYPE jsonb USING tags::jsonb"
        )
        print("   tags 변환 완료")
    else:
        print(f"   tags 이미 {tags_type}, 스킵")

    # 2. market_product_nos 컬럼 JSON → JSONB
    print("2. market_product_nos 컬럼 타입 확인 중...")
    mpn_type = await conn.fetchval(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'samba_collected_product' AND column_name = 'market_product_nos'"
    )
    print(f"   현재 market_product_nos 타입: {mpn_type}")

    if mpn_type == "json":
        print("   market_product_nos JSON → JSONB 변환 중... (시간이 걸릴 수 있음)")
        await conn.execute(
            "ALTER TABLE samba_collected_product ALTER COLUMN market_product_nos TYPE jsonb "
            "USING market_product_nos::jsonb"
        )
        print("   market_product_nos 변환 완료")
    else:
        print(f"   market_product_nos 이미 {mpn_type}, 스킵")

    # 3. GIN 인덱스 생성
    print("3. GIN 인덱스 생성 중...")
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_scp_tags_gin "
        "ON samba_collected_product USING GIN (tags)"
    )
    print("   GIN 인덱스 생성 완료")

    # 4. alembic_version 업데이트
    print("4. alembic_version 업데이트 중...")
    if ver == "zzzz_search_gin_indexes":
        await conn.execute(
            "UPDATE alembic_version SET version_num = 'zzzzz_tags_jsonb_gin' "
            "WHERE version_num = 'zzzz_search_gin_indexes'"
        )
    else:
        # 버전이 다른 경우 강제 업데이트
        await conn.execute(
            "UPDATE alembic_version SET version_num = 'zzzzz_tags_jsonb_gin'"
        )
    print("   alembic_version 업데이트 완료")

    # 최종 확인
    new_ver = await conn.fetchval("SELECT version_num FROM alembic_version LIMIT 1")
    print(f"\n마이그레이션 완료! alembic 버전: {new_ver}")

    await conn.close()


asyncio.run(main())
