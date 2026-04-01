"""add_collected_product_id_to_cs_inquiry

Revision ID: f64e3c73b22c
Revises: c4a7f2e8b1d3
Create Date: 2026-03-25 18:10:44.909389

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f64e3c73b22c"
down_revision: Union[str, Sequence[str], None] = "c4a7f2e8b1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "samba_cs_inquiry", sa.Column("collected_product_id", sa.Text(), nullable=True)
    )
    op.create_index(
        op.f("ix_samba_cs_inquiry_collected_product_id"),
        "samba_cs_inquiry",
        ["collected_product_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_samba_cs_inquiry_collected_product_id"), table_name="samba_cs_inquiry"
    )
    op.drop_column("samba_cs_inquiry", "collected_product_id")
