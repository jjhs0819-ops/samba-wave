"""samba_return에 order_number 컬럼 추가

Revision ID: r1a2b3c4d5e6
Revises: bcb782b5afaa
Create Date: 2026-03-28 21:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "r1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "bcb782b5afaa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("samba_return", sa.Column("order_number", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("samba_return", "order_number")
