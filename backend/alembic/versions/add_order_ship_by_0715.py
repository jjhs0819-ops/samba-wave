"""samba_order 에 이베이 발송기한(ship_by_at) 컬럼 추가

Revision ID: add_order_ship_by_0715
Revises: add_order_delivery_deadline_0715
Create Date: 2026-07-15
"""

import sqlalchemy as sa
from alembic import op

revision = "add_order_ship_by_0715"
down_revision = "add_order_delivery_deadline_0715"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    # hot 테이블(samba_order) ALTER 데드락 방지 — 존재 시 ALTER 스킵
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return row is not None


def upgrade() -> None:
    if not _has_column("samba_order", "ship_by_at"):
        op.add_column(
            "samba_order",
            sa.Column("ship_by_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if _has_column("samba_order", "ship_by_at"):
        op.drop_column("samba_order", "ship_by_at")
