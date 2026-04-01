"""add_market_product_nos_to_collected_product

Revision ID: 7c423005e6ab
Revises: 8742bc1e5e2c
Create Date: 2026-03-19 17:41:38.629634

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7c423005e6ab"
down_revision: Union[str, Sequence[str], None] = "8742bc1e5e2c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "samba_collected_product",
        sa.Column("market_product_nos", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("samba_collected_product", "market_product_nos")
