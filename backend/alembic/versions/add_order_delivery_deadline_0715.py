"""samba_order 에 이베이 도착기한/배송서비스코드 컬럼 추가

Revision ID: add_order_delivery_deadline_0715
Revises: add_collected_product_stock_qty_0714
Create Date: 2026-07-15
"""

import sqlalchemy as sa
from alembic import op

revision = "add_order_delivery_deadline_0715"
down_revision = "add_collected_product_stock_qty_0714"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    # hot 테이블(samba_order) ALTER 시 AccessExclusiveLock 데드락 방지 —
    # 존재하면 ALTER 자체를 스킵 (CLAUDE.md 마이그레이션 규칙)
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
    if not _has_column("samba_order", "estimated_delivery_at"):
        op.add_column(
            "samba_order",
            sa.Column(
                "estimated_delivery_at", sa.DateTime(timezone=True), nullable=True
            ),
        )
    if not _has_column("samba_order", "shipping_service_code"):
        op.add_column(
            "samba_order",
            sa.Column("shipping_service_code", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    if _has_column("samba_order", "shipping_service_code"):
        op.drop_column("samba_order", "shipping_service_code")
    if _has_column("samba_order", "estimated_delivery_at"):
        op.drop_column("samba_order", "estimated_delivery_at")
