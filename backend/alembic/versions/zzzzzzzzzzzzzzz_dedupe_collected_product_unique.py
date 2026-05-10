"""samba_collected_product NULL-safe 유니크 인덱스 (중복 수집 재발방지)

배경:
- 기존 `uq_scp_tenant_source_product (tenant_id, source_site, site_product_id)
  WHERE site_product_id IS NOT NULL`은 PostgreSQL이 NULL을 distinct로 취급하여
  tenant_id IS NULL 끼리는 동일 (source_site, site_product_id) 조합도 통과시킴.
- 프로덕션에서 28,093 그룹/46,997 row 중복 발견 (모두 tenant_id IS NULL).

수정 내용:
- 기존 `uq_scp_tenant_source_product` DROP
- COALESCE(tenant_id, '') 표현식 기반의 NULL-safe 유니크 인덱스
  `uq_scp_tenant_source_product_v2` 신규 생성

⚠️ 적용 순서 (중요):
1. 본 마이그레이션은 프로덕션 중복 row 정리 *완료 후*에 수동 적용한다.
2. 중복이 남아있는 상태로 적용하면 unique violation으로 인덱스 생성 실패.
3. CONCURRENTLY 옵션 — 큰 테이블에서 lock 회피.

Revision ID: zzzzzzzzzzzzzzz_dedupe_collected_product_unique
Revises: zzzzzzzzzzzzzz_monitor_created_at_idx
Create Date: 2026-05-10 00:00:02.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "zzzzzzzzzzzzzzz_dedupe_collected_product_unique"
down_revision: Union[str, Sequence[str], None] = "zzzzzzzzzzzzzz_monitor_created_at_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CREATE/DROP INDEX CONCURRENTLY는 트랜잭션 내부 실행 불가 → autocommit_block
    with op.get_context().autocommit_block():
        # 기존 NULL-허용 인덱스 제거
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS uq_scp_tenant_source_product")
        # NULL-safe 유니크 인덱스 생성
        op.execute(
            """
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS
                uq_scp_tenant_source_product_v2
            ON samba_collected_product (
                COALESCE(tenant_id, ''),
                source_site,
                site_product_id
            )
            WHERE site_product_id IS NOT NULL
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS uq_scp_tenant_source_product_v2")
        # 원복: 기존 NULL-unsafe 인덱스 재생성
        op.execute(
            """
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS
                uq_scp_tenant_source_product
            ON samba_collected_product (
                tenant_id,
                source_site,
                site_product_id
            )
            WHERE site_product_id IS NOT NULL
            """
        )
