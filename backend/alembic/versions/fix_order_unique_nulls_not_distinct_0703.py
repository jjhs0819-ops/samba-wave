"""fix(주문): uq_order_tenant_number_seq NULLS NOT DISTINCT 재생성 — ord_prd_seq=NULL 중복 차단

Revision ID: fix_order_unique_nulls_not_distinct_0703
Revises: add_overseas_tracking_0702
Create Date: 2026-07-03
"""

from alembic import op

revision = "fix_order_unique_nulls_not_distinct_0703"
down_revision = "add_overseas_tracking_0702"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CONCURRENTLY는 트랜잭션 밖에서 실행 필요
    op.execute("COMMIT")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS uq_order_tenant_number_seq")
    op.execute(
        """
        CREATE UNIQUE INDEX CONCURRENTLY uq_order_tenant_number_seq
        ON samba_order (tenant_id, order_number, ord_prd_seq)
        NULLS NOT DISTINCT
        """
    )


def downgrade() -> None:
    op.execute("COMMIT")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS uq_order_tenant_number_seq")
    op.execute(
        """
        CREATE UNIQUE INDEX CONCURRENTLY uq_order_tenant_number_seq
        ON samba_order (tenant_id, order_number, ord_prd_seq)
        """
    )
