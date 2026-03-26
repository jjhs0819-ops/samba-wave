"""samba_collected_product 누락 컬럼 추가 — video_url, style_code, sex, season, care_instructions, quality_guarantee

Revision ID: p4q5r6s7t8u9
Revises: o3p4q5r6s7t8
Create Date: 2026-03-26 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'p4q5r6s7t8u9'
down_revision: Union[str, Sequence[str], None] = 'o3p4q5r6s7t8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('samba_collected_product', sa.Column('video_url', sa.Text(), nullable=True))
    op.add_column('samba_collected_product', sa.Column('style_code', sa.Text(), nullable=True))
    op.add_column('samba_collected_product', sa.Column('sex', sa.Text(), nullable=True))
    op.add_column('samba_collected_product', sa.Column('season', sa.Text(), nullable=True))
    op.add_column('samba_collected_product', sa.Column('care_instructions', sa.Text(), nullable=True))
    op.add_column('samba_collected_product', sa.Column('quality_guarantee', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('samba_collected_product', 'quality_guarantee')
    op.drop_column('samba_collected_product', 'care_instructions')
    op.drop_column('samba_collected_product', 'season')
    op.drop_column('samba_collected_product', 'sex')
    op.drop_column('samba_collected_product', 'style_code')
    op.drop_column('samba_collected_product', 'video_url')
