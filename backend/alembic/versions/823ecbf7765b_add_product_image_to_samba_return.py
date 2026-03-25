"""add_product_image_to_samba_return

Revision ID: 823ecbf7765b
Revises: 355d1e221fe9
Create Date: 2026-03-25 16:36:26.056654

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '823ecbf7765b'
down_revision: Union[str, Sequence[str], None] = '355d1e221fe9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('samba_return', sa.Column('product_image', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('samba_return', 'product_image')
