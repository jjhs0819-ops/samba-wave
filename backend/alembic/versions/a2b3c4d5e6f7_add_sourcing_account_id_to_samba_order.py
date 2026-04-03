"""samba_order에 sourcing_account_id 컬럼 추가

Revision ID: a2b3c4d5e6f7
Revises: bcb782b5afaa
Create Date: 2026-03-28 22:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "bcb782b5afaa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE samba_order ADD COLUMN IF NOT EXISTS sourcing_account_id TEXT"
    )


def downgrade() -> None:
    op.drop_column("samba_order", "sourcing_account_id")
