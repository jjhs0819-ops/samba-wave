"""add free_shipping and same_day_delivery columns

Revision ID: 8355b1006c94
Revises: dd7096bd793e
Create Date: 2026-03-22 15:08:04.845939

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8355b1006c94'
down_revision: Union[str, Sequence[str], None] = 'dd7096bd793e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('samba_collected_product', sa.Column('free_shipping', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('samba_collected_product', sa.Column('same_day_delivery', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('samba_collected_product', 'same_day_delivery')
    op.drop_column('samba_collected_product', 'free_shipping')
