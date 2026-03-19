"""add_lock_fields_to_collected_product

Revision ID: c9d4e5f6a7b8
Revises: b7f3a9c2e4d1
Create Date: 2026-03-17 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b7f3a9c2e4d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """삭제잠금/재고잠금 컬럼 추가."""
    op.add_column(
        'samba_collected_product',
        sa.Column('lock_delete', sa.Boolean(), server_default='false', nullable=False),
    )
    op.add_column(
        'samba_collected_product',
        sa.Column('lock_stock', sa.Boolean(), server_default='false', nullable=False),
    )


def downgrade() -> None:
    """롤백."""
    op.drop_column('samba_collected_product', 'lock_stock')
    op.drop_column('samba_collected_product', 'lock_delete')
