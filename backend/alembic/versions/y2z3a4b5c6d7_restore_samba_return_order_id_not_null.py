"""samba_return.order_id NOT NULL 복구

Revision ID: y2z3a4b5c6d7
Revises: x1y2z3a4b5c6
Create Date: 2026-03-28 22:30:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "y2z3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "x1y2z3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NULL인 order_id 행 삭제 후 NOT NULL 복구
    op.execute("DELETE FROM samba_return WHERE order_id IS NULL")
    op.execute("ALTER TABLE samba_return ALTER COLUMN order_id SET NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE samba_return ALTER COLUMN order_id DROP NOT NULL")
