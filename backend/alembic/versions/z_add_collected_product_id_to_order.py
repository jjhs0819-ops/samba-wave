"""samba_order.collected_product_id 컬럼 추가 — 수집상품 직접 참조

Revision ID: z_order_cpid_001
Revises: z_exchange_fix_001
Create Date: 2026-04-10
"""

from typing import Sequence, Union

from alembic import op


revision: str = "z_order_cpid_001"
down_revision: Union[str, Sequence[str]] = "z_exchange_fix_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE samba_order
        ADD COLUMN IF NOT EXISTS collected_product_id TEXT
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_samba_order_collected_product_id
        ON samba_order (collected_product_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_samba_order_collected_product_id")
    op.execute("ALTER TABLE samba_order DROP COLUMN IF EXISTS collected_product_id")
