"""samba_order.sourcing_order_number 컬럼 추가

Revision ID: z3a4b5c6d7e8
Revises: y2z3a4b5c6d7
Create Date: 2026-03-29 09:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "z3a4b5c6d7e8"
down_revision: Union[str, Sequence[str], None] = ("y2z3a4b5c6d7", "a2b3c4d5e6f7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE samba_order
        ADD COLUMN IF NOT EXISTS sourcing_order_number TEXT
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE samba_order DROP COLUMN IF EXISTS sourcing_order_number")
