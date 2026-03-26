"""samba_return customer_phone check_date

Revision ID: 7e43adcea6e8
Revises: ac7aaa68958d
Create Date: 2026-03-26 08:34:23.473931

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7e43adcea6e8'
down_revision: Union[str, Sequence[str], None] = 'ac7aaa68958d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('samba_return', sa.Column('customer_phone', sa.Text(), nullable=True))
    op.add_column('samba_return', sa.Column('check_date', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('samba_return', 'check_date')
    op.drop_column('samba_return', 'customer_phone')
