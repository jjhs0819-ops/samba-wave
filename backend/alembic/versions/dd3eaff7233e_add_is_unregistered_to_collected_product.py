"""add_is_unregistered_to_collected_product

Revision ID: dd3eaff7233e
Revises: zzzzz_tags_jsonb_gin
Create Date: 2026-05-07 00:54:41.805217

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dd3eaff7233e"
down_revision: Union[str, Sequence[str], None] = "zzzzz_tags_jsonb_gin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 컬럼 추가 (idempotent)
    op.execute("""
        ALTER TABLE samba_collected_product
        ADD COLUMN IF NOT EXISTS is_unregistered BOOLEAN NOT NULL DEFAULT TRUE
    """)

    # 기존 데이터 백필: registered_accounts 기준으로 is_unregistered 계산
    op.execute("""
        UPDATE samba_collected_product
        SET is_unregistered = (
            registered_accounts IS NULL
            OR jsonb_typeof(registered_accounts) != 'array'
            OR jsonb_array_length(registered_accounts) = 0
        )
        WHERE is_unregistered = TRUE
    """)

    # 인덱스 생성 (idempotent)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_samba_collected_product_is_unregistered
        ON samba_collected_product (is_unregistered)
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS ix_samba_collected_product_is_unregistered
    """)
    op.execute("""
        ALTER TABLE samba_collected_product
        DROP COLUMN IF EXISTS is_unregistered
    """)
