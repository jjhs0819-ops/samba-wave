"""samba_detail_template에 img_checks, img_order 컬럼 추가

Revision ID: q5r6s7t8u9v0
Revises: p4q5r6s7t8u9
Create Date: 2026-03-26 00:02:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'q5r6s7t8u9v0'
down_revision: Union[str, Sequence[str], None] = 'p4q5r6s7t8u9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('samba_detail_template', sa.Column('img_checks', sa.JSON(), nullable=True))
    op.add_column('samba_detail_template', sa.Column('img_order', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('samba_detail_template', 'img_order')
    op.drop_column('samba_detail_template', 'img_checks')
