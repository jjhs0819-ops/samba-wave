"""add_shipping_fee_to_samba_order

Revision ID: 64fc7a5e6754
Revises: 693f76a3560f
Create Date: 2026-03-19 19:26:28.819682

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '64fc7a5e6754'
down_revision: Union[str, Sequence[str], None] = '693f76a3560f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('samba_order', sa.Column('shipping_fee', sa.Float(), nullable=False, server_default='0'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('samba_order', 'shipping_fee')
