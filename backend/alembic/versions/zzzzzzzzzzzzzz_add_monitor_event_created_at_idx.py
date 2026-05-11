"""add monitor_event (created_at DESC) covering index

워룸 페이지 마운트 시 호출되는 `list_recent` 쿼리는
`SELECT ... ORDER BY created_at DESC LIMIT 50` 형태로 event_type/severity
필터가 없다. 기존 인덱스는 모두 (event_type, ...) / (severity, ...) 복합이라
이 쿼리는 풀 sort를 수행 → 수백만 건 누적 시 30초~수분 소요.

`(created_at DESC)` 단독 인덱스를 추가하면 LIMIT N이 인덱스 앞부분만 스캔하여
즉시 응답.

Revision ID: zzzzzzzzzzzzzz_monitor_created_at_idx
Revises: zzzzzzzzzzzzz_monitor_partition_idx
Create Date: 2026-05-10 00:00:01.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "zzzzzzzzzzzzzz_monitor_created_at_idx"
down_revision: Union[str, Sequence[str], None] = "zzzzzzzzzzzzz_monitor_partition_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # async(asyncpg) alembic 환경에서는 autocommit_block 미지원 → AssertionError.
    # CONCURRENTLY 제거하고 단순 CREATE INDEX 으로 변경 (samba_monitor_event 102MB 라
    # 락 시간 수초 이내, 영향 미미).
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_sme_created_at_desc
        ON samba_monitor_event (created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sme_created_at_desc")
