"""add img_checks and img_order to samba_detail_template

Revision ID: r6s7t8u9v0w1
Revises: q5r6s7t8u9v0
Create Date: 2026-03-25

"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = 'r6s7t8u9v0w1'
down_revision: Union[str, Sequence[str], None] = 'q5r6s7t8u9v0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('samba_detail_template', sa.Column('img_checks', sa.JSON(), nullable=True))
    op.add_column('samba_detail_template', sa.Column('img_order', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('samba_detail_template', 'img_order')
    op.drop_column('samba_detail_template', 'img_checks')
