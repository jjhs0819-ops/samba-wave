"""add monitor_event (event_type, source_site, created_at DESC) covering index

워룸 이벤트 타임라인 쿼리(`list_latest_per_site` / `list_changes_per_site`)가
`ROW_NUMBER() OVER (PARTITION BY source_site, event_type ORDER BY created_at DESC)` 윈도우 함수를
사용하는데, 기존 `(event_type, created_at DESC)` 인덱스만으로는 partition 정렬을 위해
디스크 temp file로 외부 정렬(IO/BufFileRead 78~130초)을 수행했음.

`(event_type, source_site, created_at DESC)` 복합 인덱스를 추가하면 윈도우 함수가
인덱스 순서를 그대로 사용 → sort 단계 자체가 사라져 즉시 응답.

Revision ID: zzzzzzzzzzzzz_monitor_partition_idx
Revises: zzzzzzzzzzzz_merge_heads_lotteon_dedup_orderer_name
Create Date: 2026-05-10 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "zzzzzzzzzzzzz_monitor_partition_idx"
down_revision: Union[str, Sequence[str], None] = (
    "zzzzzzzzzzzz_merge_heads_lotteon_dedup_orderer_name"
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # autocommit_block: CREATE INDEX CONCURRENTLY는 트랜잭션 내부 실행 불가 → autocommit으로 수행
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_sme_event_site_created_at_desc
            ON samba_monitor_event (event_type, source_site, created_at DESC)
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_sme_event_site_created_at_desc"
        )
