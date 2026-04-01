"""add_sourcing_fields_to_samba_order

Revision ID: 26dd9b23892a
Revises: d985fc142e4a
Create Date: 2026-04-02 08:31:35.321270

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = '26dd9b23892a'
down_revision: Union[str, Sequence[str], None] = 'd985fc142e4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """samba_order에 sourcing_order_number, sourcing_account_id 컬럼 추가."""
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_cols = {c['name'] for c in inspector.get_columns('samba_order')}

    if 'sourcing_order_number' not in existing_cols:
        op.add_column('samba_order', sa.Column('sourcing_order_number', sa.Text(), nullable=True))
    if 'sourcing_account_id' not in existing_cols:
        op.add_column('samba_order', sa.Column('sourcing_account_id', sa.Text(), nullable=True))


def downgrade() -> None:
    """sourcing 컬럼 제거."""
    op.drop_column('samba_order', 'sourcing_account_id')
    op.drop_column('samba_order', 'sourcing_order_number')
