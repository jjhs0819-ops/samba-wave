"""samba_return에 product_location 컬럼 추가

Revision ID: 7c9a7f3b0fee
Revises: 2082f5ceb1b5
Create Date: 2026-03-26 08:57:30.657300

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c9a7f3b0fee'
down_revision: Union[str, Sequence[str], None] = '2082f5ceb1b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('samba_return', sa.Column('product_location', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('samba_return', 'product_location')
