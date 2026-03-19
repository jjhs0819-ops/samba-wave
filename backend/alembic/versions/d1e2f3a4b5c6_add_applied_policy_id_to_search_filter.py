"""add_applied_policy_id_to_search_filter

Revision ID: d1e2f3a4b5c6
Revises: c9d4e5f6a7b8
Create Date: 2026-03-17 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'c9d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """검색필터에 적용정책 ID 컬럼 추가."""
    op.add_column(
        'samba_search_filter',
        sa.Column('applied_policy_id', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """롤백."""
    op.drop_column('samba_search_filter', 'applied_policy_id')
