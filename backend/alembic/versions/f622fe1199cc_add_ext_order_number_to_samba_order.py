"""add ext_order_number to samba_order

Revision ID: f622fe1199cc
Revises: t8u9v0w1x2y3
Create Date: 2026-03-28 11:46:48.364836

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f622fe1199cc'
down_revision: Union[str, Sequence[str], None] = 't8u9v0w1x2y3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('samba_order', sa.Column('ext_order_number', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('samba_order', 'ext_order_number')
