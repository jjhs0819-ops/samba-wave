"""주문 COALESCE(paid_at, created_at) 함수형 인덱스

_build_order_sort 기본 정렬(date_desc)이 COALESCE 표현식을 사용해
기존 ix_samba_order_paid_at 인덱스를 활용하지 못하는 문제 해결.

Revision ID: z_order_coalesce_date_idx
Revises: z_tetris_board_perf_idx
Create Date: 2026-05-06 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "z_order_coalesce_date_idx"
down_revision: Union[str, Sequence[str], None] = "z_tetris_board_perf_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_samba_order_coalesce_date
        ON samba_order (COALESCE(paid_at, created_at) DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_samba_order_coalesce_date")
