"""samba_tracking_sync_job 테이블 추가 (송장 자동전송 잡 큐)

소싱처(무신사/롯데ON/SSG 등)의 배송조회 페이지를 확장앱이 열어
운송장번호를 추출 → SambaOrder.tracking_number 저장 → 마켓 dispatch
로 이어지는 파이프라인의 진행 상태 추적용.

idempotent — IF NOT EXISTS raw SQL (feedback_migration_idempotent.md 준수).
"""

from collections.abc import Sequence
from typing import Union

from alembic import op


revision: str = "zzzzzzzzzzzzzzzzzzz_add_tracking_sync_job"
down_revision: Union[str, Sequence[str], None] = (
    "zzzzzzzzzzzzzzzzzz_add_musinsa_perf_idx"
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS samba_tracking_sync_job (
            id VARCHAR(30) PRIMARY KEY,
            tenant_id VARCHAR,
            order_id TEXT NOT NULL,
            sourcing_site TEXT NOT NULL,
            sourcing_order_number TEXT NOT NULL,
            sourcing_account_id TEXT,
            owner_device_id TEXT,
            request_id TEXT,
            status TEXT NOT NULL DEFAULT 'PENDING',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            scraped_courier TEXT,
            scraped_tracking TEXT,
            scraped_at TIMESTAMPTZ,
            dispatched_to_market_at TIMESTAMPTZ,
            dispatch_result JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tsj_tenant_status "
        "ON samba_tracking_sync_job (tenant_id, status, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tsj_order ON samba_tracking_sync_job (order_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tsj_request "
        "ON samba_tracking_sync_job (request_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tsj_request")
    op.execute("DROP INDEX IF EXISTS ix_tsj_order")
    op.execute("DROP INDEX IF EXISTS ix_tsj_tenant_status")
    op.execute("DROP TABLE IF EXISTS samba_tracking_sync_job")
