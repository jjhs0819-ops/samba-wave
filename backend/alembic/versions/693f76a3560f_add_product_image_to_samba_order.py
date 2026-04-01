"""add_product_image_to_samba_order

Revision ID: 693f76a3560f
Revises: 7c423005e6ab
Create Date: 2026-03-19 19:09:31.351821

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "693f76a3560f"
down_revision: Union[str, Sequence[str], None] = "7c423005e6ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("samba_order", sa.Column("product_image", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("samba_order", "product_image")
