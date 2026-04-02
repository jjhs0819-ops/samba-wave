"""add_market_product_no_to_cs_inquiry

Revision ID: 9f8e7d6c5b4a
Revises: f64e3c73b22c
Create Date: 2026-03-25 18:43:01.996601

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9f8e7d6c5b4a"
down_revision: Union[str, Sequence[str], None] = "f64e3c73b22c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "samba_cs_inquiry", sa.Column("market_product_no", sa.Text(), nullable=True)
    )
    op.create_index(
        op.f("ix_samba_cs_inquiry_market_product_no"),
        "samba_cs_inquiry",
        ["market_product_no"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_samba_cs_inquiry_market_product_no"), table_name="samba_cs_inquiry"
    )
    op.drop_column("samba_cs_inquiry", "market_product_no")
