"""applied_policy_id 인덱스 추가

Revision ID: 89c6e7df240e
Revises: 6497c73e78e8
Create Date: 2026-03-24 23:34:30.466757

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '89c6e7df240e'
down_revision: Union[str, Sequence[str], None] = '6497c73e78e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(op.f('ix_samba_collected_product_applied_policy_id'), 'samba_collected_product', ['applied_policy_id'], unique=False)
    op.create_index(op.f('ix_samba_search_filter_applied_policy_id'), 'samba_search_filter', ['applied_policy_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_samba_search_filter_applied_policy_id'), table_name='samba_search_filter')
    op.drop_index(op.f('ix_samba_collected_product_applied_policy_id'), table_name='samba_collected_product')
