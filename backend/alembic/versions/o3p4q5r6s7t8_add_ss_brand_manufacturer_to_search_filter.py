"""add ss_brand_manufacturer to search_filter

Revision ID: o3p4q5r6s7t8
Revises: n2o3p4q5r6s7
Create Date: 2026-03-25

"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = 'o3p4q5r6s7t8'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('samba_search_filter', sa.Column('ss_brand_id', sa.Integer(), nullable=True))
    op.add_column('samba_search_filter', sa.Column('ss_brand_name', sa.Text(), nullable=True))
    op.add_column('samba_search_filter', sa.Column('ss_manufacturer_id', sa.Integer(), nullable=True))
    op.add_column('samba_search_filter', sa.Column('ss_manufacturer_name', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('samba_search_filter', 'ss_manufacturer_name')
    op.drop_column('samba_search_filter', 'ss_manufacturer_id')
    op.drop_column('samba_search_filter', 'ss_brand_name')
    op.drop_column('samba_search_filter', 'ss_brand_id')
