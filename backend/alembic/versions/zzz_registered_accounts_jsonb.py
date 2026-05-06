"""registered_accounts JSON → JSONB 변환 + GIN 인덱스

registered_accounts 컬럼을 JSON에서 JSONB로 변환하고 GIN 인덱스를 추가해
마켓 등록 필터링 쿼리(cast+LIKE)를 @> 연산자로 교체할 수 있도록 한다.

Revision ID: zzz_registered_accounts_jsonb
Revises: z_order_coalesce_date_idx
Create Date: 2026-05-06 12:00:00.000000
"""

from alembic import op

revision = "zzz_registered_accounts_jsonb"
down_revision = "z_order_coalesce_date_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 컬럼 타입 JSON → JSONB (이미 JSONB면 스킵)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'samba_collected_product'
                  AND column_name = 'registered_accounts'
                  AND data_type = 'json'
            ) THEN
                ALTER TABLE samba_collected_product
                    ALTER COLUMN registered_accounts
                    TYPE JSONB USING registered_accounts::jsonb;
            END IF;
        END $$;
    """)

    # GIN 인덱스 추가 (@> 연산자 가속)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scp_registered_accounts_gin
        ON samba_collected_product USING GIN (registered_accounts);
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS ix_scp_registered_accounts_gin;
    """)
    op.execute("""
        ALTER TABLE samba_collected_product
            ALTER COLUMN registered_accounts
            TYPE JSON USING registered_accounts::text::json;
    """)
