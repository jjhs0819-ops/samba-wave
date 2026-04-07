"""add_sort_order_to_market_account

Revision ID: 8c61d687b4ab
Revises: 2c0a9e7fbdfe
Create Date: 2026-04-06 16:39:07.237667

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "8c61d687b4ab"
down_revision: Union[str, Sequence[str], None] = "2c0a9e7fbdfe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "samba_market_account",
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("samba_market_account", "sort_order")
