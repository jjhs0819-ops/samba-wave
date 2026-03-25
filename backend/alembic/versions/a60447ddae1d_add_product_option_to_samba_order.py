"""add_product_option_to_samba_order

Revision ID: a60447ddae1d
Revises: 9f8e7d6c5b4a
Create Date: 2026-03-25 18:49:37.651010

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a60447ddae1d'
down_revision: Union[str, Sequence[str], None] = '9f8e7d6c5b4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('samba_order', sa.Column('product_option', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('samba_order', 'product_option')
