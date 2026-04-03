"""samba_order.sourcing_account_id 컬럼 추가 및 두 브랜치 머지

Revision ID: b9c8d7e6f5a4
Revises: d985fc142e4a, z3a4b5c6d7e8
Create Date: 2026-04-01 10:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b9c8d7e6f5a4"
down_revision: Union[str, Sequence[str], None] = ("d985fc142e4a", "z3a4b5c6d7e8")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE samba_order
        ADD COLUMN IF NOT EXISTS sourcing_account_id TEXT;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE samba_order
        DROP COLUMN IF EXISTS sourcing_account_id;
    """)
