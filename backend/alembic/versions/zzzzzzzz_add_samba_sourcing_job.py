"""samba_sourcing_job 테이블 추가 — 소싱 잡 영속화 1단계.

현재는 빈 테이블만 생성. 실제 SourcingQueue dual-write/read 전환은 후속 PR.
재배포 시 안전하도록 IF NOT EXISTS 로 idempotent 보장.

Revision ID: zzzzzzzz_add_samba_sourcing_job
Revises: zzzzzzz_drop_is_unregistered
Create Date: 2026-05-09
"""

from alembic import op


revision = "zzzzzzzz_add_samba_sourcing_job"
down_revision = "zzzzzzz_drop_is_unregistered"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 테이블 신설 — 기존 동작 영향 없음 (빈 테이블)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS samba_sourcing_job (
            request_id VARCHAR(64) PRIMARY KEY,
            site VARCHAR(32) NOT NULL,
            job_type VARCHAR(32) NOT NULL DEFAULT 'detail',
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            owner_device_id VARCHAR(64),
            payload JSON,
            result JSON,
            error TEXT,
            attempt INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            dispatched_at TIMESTAMP WITH TIME ZONE,
            completed_at TIMESTAMP WITH TIME ZONE,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """
    )
    # 폴링/만료 처리에 사용될 인덱스
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_samba_sourcing_job_site ON samba_sourcing_job (site)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_samba_sourcing_job_status ON samba_sourcing_job (status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_samba_sourcing_job_owner_device_id ON samba_sourcing_job (owner_device_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_samba_sourcing_job_expires_at ON samba_sourcing_job (expires_at)"
    )
    # 만료된 pending/dispatched 잡 일괄 청소용 부분 인덱스
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_samba_sourcing_job_active_expiry
        ON samba_sourcing_job (expires_at)
        WHERE status IN ('pending', 'dispatched')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_samba_sourcing_job_active_expiry")
    op.execute("DROP INDEX IF EXISTS ix_samba_sourcing_job_expires_at")
    op.execute("DROP INDEX IF EXISTS ix_samba_sourcing_job_owner_device_id")
    op.execute("DROP INDEX IF EXISTS ix_samba_sourcing_job_status")
    op.execute("DROP INDEX IF EXISTS ix_samba_sourcing_job_site")
    op.execute("DROP TABLE IF EXISTS samba_sourcing_job")
