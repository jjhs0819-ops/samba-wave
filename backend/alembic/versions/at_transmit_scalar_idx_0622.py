"""autotune_transmit scalar 부분식 인덱스 — dedup/claim O(pending)→O(1) (#462)

Revision ID: at_transmit_scalar_idx_0622
Revises: at_transmit_pending_idx_0620
Create Date: 2026-06-22

autotune_transmit payload 는 항상 단일원소(product_ids:[pid]/target_account_ids:[acc]).
dedup(_enqueue_autotune_transmit)와 account-lock(claim_autotune_pending_job)이
json_array_elements_text/unnest 배열연산이라 집중 pending 부하에서 O(pending).
scalar `->>0` 비교로 전환하면서 부분식 인덱스로 발행단 dedup 조회를 O(1) walk 로.

payload 컬럼은 json 타입(jsonb 아님)이나 `->`/`->>` 연산자·표현식 인덱스 지원됨.
"""

from alembic import op

revision = "at_transmit_scalar_idx_0622"
down_revision = "at_transmit_pending_idx_0620"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CONCURRENTLY 는 트랜잭션 밖에서 실행 필요
    op.execute("COMMIT")
    op.execute(
        """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_samba_jobs_autotune_pending_pid
        ON samba_jobs ((payload->'product_ids'->>0))
        WHERE status = 'pending' AND job_type = 'autotune_transmit'
        """
    )
    op.execute(
        """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_samba_jobs_autotune_pending_acc
        ON samba_jobs ((payload->'target_account_ids'->>0))
        WHERE status = 'pending' AND job_type = 'autotune_transmit'
        """
    )


def downgrade() -> None:
    op.execute("COMMIT")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_samba_jobs_autotune_pending_pid")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_samba_jobs_autotune_pending_acc")
