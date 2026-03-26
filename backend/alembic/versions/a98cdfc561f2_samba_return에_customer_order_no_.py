"""samba_return에 customer_order_no, original_order_no 추가

Revision ID: a98cdfc561f2
Revises: 7c9a7f3b0fee
Create Date: 2026-03-26 09:08:23.934437

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a98cdfc561f2'
down_revision: Union[str, Sequence[str], None] = '7c9a7f3b0fee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('samba_return', sa.Column('customer_order_no', sa.Text(), nullable=True))
    op.add_column('samba_return', sa.Column('original_order_no', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('samba_return', 'original_order_no')
    op.drop_column('samba_return', 'customer_order_no')
