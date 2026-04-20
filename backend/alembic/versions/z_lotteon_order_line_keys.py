"""samba_order 롯데ON 라인키 컬럼 추가 (od_no, od_seq, proc_seq, sitm_no)

Revision ID: z_lotteon_order_line_keys
Revises: z3a4b5c6d7e8
Create Date: 2026-04-20 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "z_lotteon_order_line_keys"
down_revision: Union[str, None] = "z3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1단계: 컬럼 추가 (모두 nullable)
    op.add_column("samba_order", sa.Column("od_no", sa.Text(), nullable=True))
    op.add_column("samba_order", sa.Column("od_seq", sa.Text(), nullable=True))
    op.add_column("samba_order", sa.Column("proc_seq", sa.Text(), nullable=True))
    op.add_column("samba_order", sa.Column("sitm_no", sa.Text(), nullable=True))

    # 2단계: 기존 lotteon 행 backfill (od_no=order_number, od_seq='1', proc_seq='1')
    op.execute("""
        UPDATE samba_order
        SET od_no = order_number, od_seq = '1', proc_seq = '1'
        WHERE source = 'lotteon' AND od_no IS NULL
    """)

    # 3단계: partial unique 인덱스 (lotteon 전용)
    op.create_index(
        "ix_samba_order_lotteon_line",
        "samba_order",
        ["tenant_id", "channel_id", "od_no", "od_seq", "proc_seq"],
        unique=True,
        postgresql_where=sa.text("source = 'lotteon'"),
    )


def downgrade() -> None:
    op.drop_index("ix_samba_order_lotteon_line", table_name="samba_order")
    op.drop_column("samba_order", "sitm_no")
    op.drop_column("samba_order", "proc_seq")
    op.drop_column("samba_order", "od_seq")
    op.drop_column("samba_order", "od_no")
