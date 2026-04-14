"""add_paid_at_index_to_samba_order

Revision ID: 91c5a0e05167
Revises: 1dea0f1eb6e4
Create Date: 2026-04-14 12:32:36.132146

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "91c5a0e05167"
down_revision: Union[str, Sequence[str], None] = "1dea0f1eb6e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """paid_at 컬럼에 인덱스 추가 — 대시보드/날짜 범위 조회 풀 스캔 방지."""
    op.create_index(
        op.f("ix_samba_order_paid_at"),
        "samba_order",
        ["paid_at"],
        unique=False,
    )


def downgrade() -> None:
    """paid_at 인덱스 제거."""
    op.drop_index(op.f("ix_samba_order_paid_at"), table_name="samba_order")
