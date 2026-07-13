"""feat(고정가등록): samba_collected_product.price_locked, locked_prices 추가

- price_locked=True면 오토튠/전송 시 정책 공식 재계산 없이 locked_prices[account_id]
  값을 최종 판매가로 사용 (이베이 등 소싱원가 변동과 무관하게 고정가 유지 요청 대응).

Revision ID: add_collected_product_price_lock_0713
Revises: fix_order_unique_nulls_not_distinct_0703
Create Date: 2026-07-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "add_collected_product_price_lock_0713"
down_revision = "fix_order_unique_nulls_not_distinct_0703"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # hot 테이블 데드락 방지 — 컬럼 존재 여부 확인 후 없을 때만 ALTER
    conn = op.get_bind()
    existing = {
        row[0]
        for row in conn.exec_driver_sql(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'samba_collected_product' "
            "AND column_name IN ('price_locked', 'locked_prices')"
        )
    }
    if "price_locked" not in existing:
        op.add_column(
            "samba_collected_product",
            sa.Column(
                "price_locked",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if "locked_prices" not in existing:
        op.add_column(
            "samba_collected_product",
            sa.Column(
                "locked_prices",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )


def downgrade() -> None:
    op.drop_column("samba_collected_product", "locked_prices")
    op.drop_column("samba_collected_product", "price_locked")
