"""samba_return 누락 컬럼 일괄 추가 (IF NOT EXISTS)

Revision ID: w2x3y4z5a6b7
Revises: v1a2b3c4d5e6
Create Date: 2026-03-28 21:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'w2x3y4z5a6b7'
down_revision: Union[str, Sequence[str], None] = 'v1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS 방식으로 안전하게 추가
    op.execute("ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS product_image TEXT")
    op.execute("ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS product_name TEXT")
    op.execute("ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS customer_name TEXT")
    op.execute("ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS business_name TEXT")
    op.execute("ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS market TEXT")
    op.execute("ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS customer_phone TEXT")
    op.execute("ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS confirmed BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS order_date TIMESTAMPTZ")
    op.execute("ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS check_date TIMESTAMPTZ")
    op.execute("ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS settlement_amount FLOAT")
    op.execute("ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS recovery_amount FLOAT")
    op.execute("ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS memo TEXT")
    op.execute("ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS product_location TEXT")
    op.execute("ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS customer_address TEXT")
    op.execute("ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS market_order_status TEXT")
    op.execute("ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS completion_detail TEXT DEFAULT '진행중'")
    op.execute("ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS customer_order_no TEXT DEFAULT 'return_incomplete'")
    op.execute("ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS original_order_no TEXT DEFAULT 'return_incomplete'")


def downgrade() -> None:
    pass
