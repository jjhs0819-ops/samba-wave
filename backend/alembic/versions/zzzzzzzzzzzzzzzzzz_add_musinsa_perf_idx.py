"""samba_collected_product (status, source_site, last_refreshed_at) 복합 인덱스 추가

MUSINSA 48,428건처럼 사이트별 등록상품이 많을 때 사이트 루프 진입 시
last_refreshed_at ASC 정렬을 인덱스로 처리해 SELECT 시간 단축.

EXPLAIN 측정(2026-05-12):
  before: Bitmap Heap Scan + Sort → 245ms (15,050 페이지 random read)
  after : Index Scan → 수십 ms 예상

idempotent — IF NOT EXISTS, CONCURRENTLY로 다운타임 없음.
"""

from collections.abc import Sequence
from typing import Union

from alembic import op


revision: str = "zzzzzzzzzzzzzzzzzz_add_musinsa_perf_idx"
down_revision: Union[str, Sequence[str], None] = (
    "zzzzzzzzzzzzzzzzz_add_market_registered_tracking"
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CONCURRENTLY는 트랜잭션 안에서 못 돌리므로 autocommit 모드로 실행
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_scp_status_source_last_refreshed "
            "ON samba_collected_product "
            "(status, source_site, last_refreshed_at ASC NULLS FIRST)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_scp_status_source_last_refreshed"
        )
