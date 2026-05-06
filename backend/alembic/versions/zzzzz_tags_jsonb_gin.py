"""tags/market_product_nos JSON→JSONB 변환 + tags GIN 인덱스 추가

드릴다운 메뉴 30초 로딩 원인: cast(tags, String).like('%...%') 풀 테이블 스캔.
JSONB @> 연산자 + GIN 인덱스로 대체.

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
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'samba_collected_product'
                  AND column_name = 'tags'
                  AND data_type = 'json'
            ) THEN
                ALTER TABLE samba_collected_product
                    ALTER COLUMN tags TYPE jsonb USING tags::jsonb;
            END IF;
        END
        $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'samba_collected_product'
                  AND column_name = 'market_product_nos'
                  AND data_type = 'json'
            ) THEN
                ALTER TABLE samba_collected_product
                    ALTER COLUMN market_product_nos TYPE jsonb USING market_product_nos::jsonb;
            END IF;
        END
        $$;
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scp_tags_gin
        ON samba_collected_product USING GIN (tags);
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
