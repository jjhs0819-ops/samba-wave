"""samba_return.order_id nullable 허용 (주문 없는 반품/취소 저장 지원)

Revision ID: x1y2z3a4b5c6
Revises: w2x3y4z5a6b7
Create Date: 2026-03-28 22:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'x1y2z3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'w2x3y4z5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE samba_return ALTER COLUMN order_id DROP NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE samba_return ALTER COLUMN order_id SET NOT NULL")
