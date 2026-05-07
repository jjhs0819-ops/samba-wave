"""tags/market_product_nos JSON→JSONB 변환 + tags GIN 인덱스 추가

드릴다운 메뉴 30초 로딩 원인: cast(tags, String).like('%...%') 풀 테이블 스캔.
JSONB @> 연산자 + GIN 인덱스로 대체.

블루/그린 배포 deadlock 회피: ALTER COLUMN TYPE 가 AccessExclusiveLock 을 잡고,
운영 중인 blue 컨테이너의 RowExclusiveLock 과 deadlock 발생 (2026-05-07 사고).
→ lock_timeout + retry 로 운영 중에도 안전하게 적용.

Revision ID: zzzzz_tags_jsonb_gin
Revises: zzzz_search_gin_indexes
Create Date: 2026-05-07 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "zzzzz_tags_jsonb_gin"
down_revision: Union[str, Sequence[str], None] = "zzzz_search_gin_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        DO $$
        DECLARE
            attempts INTEGER := 0;
            max_attempts INTEGER := 30;
        BEGIN
            LOOP
                attempts := attempts + 1;
                BEGIN
                    SET LOCAL lock_timeout = '3s';
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'samba_collected_product'
                          AND column_name = 'tags'
                          AND data_type = 'json'
                    ) THEN
                        ALTER TABLE samba_collected_product
                            ALTER COLUMN tags TYPE jsonb USING tags::jsonb;
                    END IF;
                    EXIT;
                EXCEPTION
                    WHEN lock_not_available OR deadlock_detected THEN
                        IF attempts >= max_attempts THEN RAISE; END IF;
                        PERFORM pg_sleep(2);
                END;
            END LOOP;
        END
        $$;
    """)

    op.execute("""
        DO $$
        DECLARE
            attempts INTEGER := 0;
            max_attempts INTEGER := 30;
        BEGIN
            LOOP
                attempts := attempts + 1;
                BEGIN
                    SET LOCAL lock_timeout = '3s';
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'samba_collected_product'
                          AND column_name = 'market_product_nos'
                          AND data_type = 'json'
                    ) THEN
                        ALTER TABLE samba_collected_product
                            ALTER COLUMN market_product_nos TYPE jsonb USING market_product_nos::jsonb;
                    END IF;
                    EXIT;
                EXCEPTION
                    WHEN lock_not_available OR deadlock_detected THEN
                        IF attempts >= max_attempts THEN RAISE; END IF;
                        PERFORM pg_sleep(2);
                END;
            END LOOP;
        END
        $$;
    """)

    op.execute("""
        DO $$
        DECLARE
            attempts INTEGER := 0;
            max_attempts INTEGER := 30;
        BEGIN
            LOOP
                attempts := attempts + 1;
                BEGIN
                    SET LOCAL lock_timeout = '3s';
                    CREATE INDEX IF NOT EXISTS ix_scp_tags_gin
                        ON samba_collected_product USING GIN (tags);
                    EXIT;
                EXCEPTION
                    WHEN lock_not_available OR deadlock_detected THEN
                        IF attempts >= max_attempts THEN RAISE; END IF;
                        PERFORM pg_sleep(2);
                END;
            END LOOP;
        END
        $$;
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_scp_tags_gin;")

    op.execute("""
        ALTER TABLE samba_collected_product
            ALTER COLUMN tags TYPE json USING tags::json;
    """)

    op.execute("""
        ALTER TABLE samba_collected_product
            ALTER COLUMN market_product_nos TYPE json USING market_product_nos::json;
    """)
