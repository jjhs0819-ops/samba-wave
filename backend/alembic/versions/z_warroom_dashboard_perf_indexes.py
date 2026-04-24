"""add warroom dashboard performance indexes

오토튠(워룸) 페이지 로딩 1분 이슈 개선.
- monitor/dashboard 병목 쿼리 전부 커버
- samba_collected_product: (source_site, monitor_priority, sale_status) 복합 GROUP BY
- samba_collected_product: last_refreshed_at, refresh_error_count (부분 인덱스)
- samba_monitor_event: (event_type, created_at DESC), (severity, created_at DESC)
- samba_settings: key LIKE 'probe_%' 대응용 text_pattern_ops (현재 PK가 key여서 별도 불필요)

Revision ID: z_warroom_dashboard_idx
Revises: zz_merge_ebay_and_dedup
Create Date: 2026-04-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "z_warroom_dashboard_idx"
down_revision: Union[str, Sequence[str], None] = "zz_merge_ebay_and_dedup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_scp_source_priority_sale_status
        ON samba_collected_product (source_site, monitor_priority, sale_status)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_scp_last_refreshed_at
        ON samba_collected_product (last_refreshed_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_scp_refresh_error_partial
        ON samba_collected_product (id)
        WHERE refresh_error_count > 0
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_sme_event_type_created_at_desc
        ON samba_monitor_event (event_type, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_sme_severity_created_at_desc
        ON samba_monitor_event (severity, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sme_severity_created_at_desc")
    op.execute("DROP INDEX IF EXISTS ix_sme_event_type_created_at_desc")
    op.execute("DROP INDEX IF EXISTS ix_scp_refresh_error_partial")
    op.execute("DROP INDEX IF EXISTS ix_scp_last_refreshed_at")
    op.execute("DROP INDEX IF EXISTS ix_scp_source_priority_sale_status")
