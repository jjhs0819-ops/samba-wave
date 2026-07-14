"""feat(재고설정): samba_collected_product.stock_quantities 추가

- {account_id: qty} — 마켓별 등록 재고수량 명시 지정. 미설정 시 기본 1개(무재고
  위탁판매 오버셀 방지 기본값 유지), 사용자가 소싱처에서 여러 개 확보 가능한
  상품에 한해 명시적으로 늘릴 수 있게 함.

Revision ID: add_collected_product_stock_qty_0714
Revises: add_collected_product_price_lock_0713
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "add_collected_product_stock_qty_0714"
down_revision = "add_collected_product_price_lock_0713"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = {
        row[0]
        for row in conn.exec_driver_sql(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'samba_collected_product' "
            "AND column_name = 'stock_quantities'"
        )
    }
    if "stock_quantities" not in existing:
        op.add_column(
            "samba_collected_product",
            sa.Column(
                "stock_quantities",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )


def downgrade() -> None:
    op.drop_column("samba_collected_product", "stock_quantities")
