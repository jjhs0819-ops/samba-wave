"""add_detail_images_to_collected_product

Revision ID: 8742bc1e5e2c
Revises: ce18b9247535
Create Date: 2026-03-19 16:37:41.423326

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8742bc1e5e2c'
down_revision: Union[str, Sequence[str], None] = 'ce18b9247535'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('samba_collected_product', sa.Column('detail_images', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('samba_collected_product', 'detail_images')
