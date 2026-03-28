"""소싱처 계정 테이블 추가

Revision ID: u9v0w1x2y3z4
Revises: 4f3493e4d2ef
Create Date: 2026-03-28 20:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'u9v0w1x2y3z4'
down_revision: Union[str, Sequence[str], None] = '4f3493e4d2ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'samba_sourcing_account',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('tenant_id', sa.String(), nullable=True, index=True),
        sa.Column('site_name', sa.Text(), nullable=False, index=True),
        sa.Column('account_label', sa.Text(), nullable=False),
        sa.Column('username', sa.Text(), nullable=False),
        sa.Column('password', sa.Text(), nullable=False),
        sa.Column('chrome_profile', sa.Text(), nullable=True),
        sa.Column('memo', sa.Text(), nullable=True),
        sa.Column('balance', sa.Float(), nullable=True),
        sa.Column('balance_updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true', index=True),
        sa.Column('additional_fields', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('samba_sourcing_account')
