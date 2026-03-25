"""add composite index status_source_site

Revision ID: 4895f1d6be8d
Revises: d01f26874b32
Create Date: 2026-03-24 19:31:10.964552

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '4895f1d6be8d'
down_revision: Union[str, Sequence[str], None] = 'd01f26874b32'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """status + source_site 복합 인덱스 추가 (복합 필터링 성능 개선)."""
    op.create_index('ix_scp_status_source_site', 'samba_collected_product', ['status', 'source_site'], unique=False)


def downgrade() -> None:
    """복합 인덱스 제거."""
    op.drop_index('ix_scp_status_source_site', table_name='samba_collected_product')
