"""add source_url to samba_order

Revision ID: 4f3493e4d2ef
Revises: 6c98b0a38d90
Create Date: 2026-03-28 11:59:51.163885

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4f3493e4d2ef"
down_revision: Union[str, Sequence[str], None] = "6c98b0a38d90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("samba_order", sa.Column("source_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("samba_order", "source_url")
