"""로컬 DB: is_unregistered 컬럼 추가 마이그레이션 (lock_timeout 우회)"""
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

    ver = await conn.fetchval("SELECT version_num FROM alembic_version LIMIT 1")
    print(f"현재 alembic 버전: {ver}")

    if ver == "dd3eaff7233e":
        print("이미 마이그레이션 완료됨. 종료.")
        await conn.close()
        return

    await conn.execute("SET lock_timeout = 0")
    print("lock_timeout 해제")

    # 컬럼 확인
    col = await conn.fetchval(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'samba_collected_product' AND column_name = 'is_unregistered'"
    )

    if not col:
        print("is_unregistered 컬럼 추가 중...")
        await conn.execute(
            "ALTER TABLE samba_collected_product "
            "ADD COLUMN IF NOT EXISTS is_unregistered BOOLEAN NOT NULL DEFAULT TRUE"
        )
        print("컬럼 추가 완료")

        print("기존 데이터 백필 중... (시간이 걸릴 수 있음)")
        updated = await conn.execute(
            """
            UPDATE samba_collected_product
            SET is_unregistered = (
                registered_accounts IS NULL
                OR jsonb_typeof(registered_accounts) != 'array'
                OR jsonb_array_length(registered_accounts) = 0
            )
            WHERE is_unregistered = TRUE
            """
        )
        print(f"백필 완료: {updated}")
    else:
        print("is_unregistered 컬럼 이미 존재, 스킵")

    # 인덱스 생성
    print("인덱스 생성 중...")
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_samba_collected_product_is_unregistered "
        "ON samba_collected_product (is_unregistered)"
    )
    print("인덱스 생성 완료")

    # alembic_version 업데이트
    await conn.execute(
        "UPDATE alembic_version SET version_num = 'dd3eaff7233e'"
    )

    new_ver = await conn.fetchval("SELECT version_num FROM alembic_version LIMIT 1")
    print(f"\n마이그레이션 완료! alembic 버전: {new_ver}")

    await conn.close()


asyncio.run(main())
