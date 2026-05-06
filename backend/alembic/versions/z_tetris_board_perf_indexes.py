"""테트리스 보드 로딩 성능 개선 인덱스

- (tenant_id, source_site, BTRIM(brand)) 함수형 복합 인덱스
  → get_board() 두 집계 쿼리의 풀스캔 제거
- registered_accounts GIN 인덱스
  → jsonb_array_elements_text 필터링 최적화

Revision ID: z_tetris_board_perf_idx
Revises: 4ba0175594e8
Create Date: 2026-05-06 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "z_tetris_board_perf_idx"
down_revision: Union[str, Sequence[str], None] = "4ba0175594e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # BTRIM(brand) 함수형 복합 인덱스 — GROUP BY source_site, BTRIM(brand) 최적화
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scp_tenant_site_brand_trim
        ON samba_collected_product (tenant_id, source_site, BTRIM(brand))
        WHERE brand IS NOT NULL AND BTRIM(brand) != ''
    """)

    # registered_accounts GIN 인덱스 — jsonb 연산 최적화
    # WHERE 조건: 정규식으로 '[...]' 배열 형태의 유효 JSON만 인덱싱
    # (불완전한 JSON/빈 문자열은 ::jsonb 캐스트 실패 → invalid input syntax 방지)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scp_registered_accounts_gin
        ON samba_collected_product
        USING GIN ((registered_accounts::jsonb) jsonb_ops)
        WHERE registered_accounts IS NOT NULL
          AND registered_accounts ~ '^\\[.+\\]$'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_scp_registered_accounts_gin")
    op.execute("DROP INDEX IF EXISTS ix_scp_tenant_site_brand_trim")
