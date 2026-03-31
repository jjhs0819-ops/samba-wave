"""add video_url to collected_product

Revision ID: p4q5r6s7t8u9
Revises: o3p4q5r6s7t8
Create Date: 2026-03-25

"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = 'p4q5r6s7t8u9'
down_revision: Union[str, Sequence[str], None] = 'o3p4q5r6s7t8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('samba_collected_product', sa.Column('video_url', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('samba_collected_product', 'video_url')
