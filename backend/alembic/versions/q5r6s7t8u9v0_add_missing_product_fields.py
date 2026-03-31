"""add missing product fields (style_code, sex, season, care_instructions, quality_guarantee)

Revision ID: q5r6s7t8u9v0
Revises: p4q5r6s7t8u9
Create Date: 2026-03-25

"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = 'q5r6s7t8u9v0'
down_revision: Union[str, Sequence[str], None] = 'p4q5r6s7t8u9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('samba_collected_product', sa.Column('style_code', sa.String(), nullable=True))
    op.add_column('samba_collected_product', sa.Column('sex', sa.String(), nullable=True))
    op.add_column('samba_collected_product', sa.Column('season', sa.String(), nullable=True))
    op.add_column('samba_collected_product', sa.Column('care_instructions', sa.Text(), nullable=True))
    op.add_column('samba_collected_product', sa.Column('quality_guarantee', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('samba_collected_product', 'quality_guarantee')
    op.drop_column('samba_collected_product', 'care_instructions')
    op.drop_column('samba_collected_product', 'season')
    op.drop_column('samba_collected_product', 'sex')
    op.drop_column('samba_collected_product', 'style_code')
