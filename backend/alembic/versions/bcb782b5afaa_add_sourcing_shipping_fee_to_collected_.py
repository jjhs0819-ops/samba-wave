"""add sourcing_shipping_fee to collected_product

Revision ID: bcb782b5afaa
Revises: u9v0w1x2y3z4
Create Date: 2026-03-28 13:49:11.638183

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'bcb782b5afaa'
down_revision: Union[str, Sequence[str], None] = 'u9v0w1x2y3z4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('samba_collected_product', sa.Column('sourcing_shipping_fee', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('samba_collected_product', 'sourcing_shipping_fee')
