"""samba_order.action_tag 컬럼 추가 — 가격X/재고X/직배/까대기/선물 태그 저장

Revision ID: z_action_tag_001
Revises: z_fix_autotune_001
Create Date: 2026-04-10
"""

from typing import Sequence, Union

from alembic import op


revision: str = "z_action_tag_001"
down_revision: Union[str, Sequence[str]] = "z_fix_autotune_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE samba_order
        ADD COLUMN IF NOT EXISTS action_tag TEXT
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE samba_order DROP COLUMN IF EXISTS action_tag")
