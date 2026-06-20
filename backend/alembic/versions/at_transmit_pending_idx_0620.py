"""autotune_transmit pending 부분 인덱스 추가 — claim O(1) 최적화 (#459)

Revision ID: at_transmit_pending_idx_0620
Revises: sc_saved_products_0618
Create Date: 2026-06-20

claim_pending_job 의 CASE 정렬키 3종이 job_type='transmit' 게이트라
autotune_transmit 에서 전부 0(상수) → 실제 정렬은 created_at 뿐.
부분 인덱스로 pending autotune_transmit 만 소규모 인덱스 walk → 5,035ms → 0.25ms.
"""

from alembic import op

revision = "at_transmit_pending_idx_0620"
down_revision = "sc_saved_products_0618"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CONCURRENTLY 는 트랜잭션 밖에서 실행 필요
    op.execute("COMMIT")
    op.execute(
        """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_samba_jobs_autotune_pending
        ON samba_jobs (created_at)
        WHERE status = 'pending' AND job_type = 'autotune_transmit'
        """
    )


def downgrade() -> None:
    op.execute("COMMIT")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_samba_jobs_autotune_pending")
