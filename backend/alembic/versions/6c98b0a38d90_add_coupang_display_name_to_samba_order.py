"""add coupang_display_name to samba_order

Revision ID: 6c98b0a38d90
Revises: f622fe1199cc
Create Date: 2026-03-28 11:53:38.554640

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6c98b0a38d90'
down_revision: Union[str, Sequence[str], None] = 'f622fe1199cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('samba_order', sa.Column('coupang_display_name', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('samba_order', 'coupang_display_name')
