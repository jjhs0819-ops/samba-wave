"""add_product_image_to_samba_cs_inquiry

Revision ID: 355d1e221fe9
Revises: b1c2d3e4f5a6
Create Date: 2026-03-25 16:31:59.568846

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '355d1e221fe9'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('samba_cs_inquiry', sa.Column('product_image', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('samba_cs_inquiry', 'product_image')
