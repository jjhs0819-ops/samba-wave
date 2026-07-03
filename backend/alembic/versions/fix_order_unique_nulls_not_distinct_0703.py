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
    # 존재가드: 이미 NULLS NOT DISTINCT 인덱스가 있으면 DROP/재생성하지 않고 즉시 종료.
    # 매 부팅 entrypoint의 alembic upgrade가 이 마이그레이션을 재실행할 때
    # 멀쩡한 인덱스를 DROP → CONCURRENTLY 재생성하다 열린 트랜잭션(잡워커 idle-in-tx)에
    # 막혀 lock timeout → 부팅 실패 → 컨테이너 크래시 루프(서버 다운) 유발하던 것 차단.
    conn = op.get_bind()
    already = conn.exec_driver_sql(
        "SELECT 1 FROM pg_indexes "
        "WHERE indexname = 'uq_order_tenant_number_seq' "
        "AND indexdef ILIKE '%NULLS NOT DISTINCT%'"
    ).scalar()
    if already:
        return
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
