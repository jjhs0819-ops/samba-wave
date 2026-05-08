"""롯데ON 주문 중복 수정 — order_number에서 procSeq 제거 + 중복 행 정리

procSeq는 처리 단계에 따라 변하는 값이라 order_number 키로 부적합.
기존 중복 행 정리 후 ix_samba_order_lotteon_line 인덱스 재구성.

Revision ID: zzzzzz_lotteon_order_dedup_fix
Revises: zzzzz_tags_jsonb_gin
Create Date: 2026-05-07 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "zzzzzz_lotteon_order_dedup_fix"
down_revision: Union[str, Sequence[str], None] = "zzzzz_tags_jsonb_gin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. od_no+od_seq 기준 중복 행 정리 (procSeq가 달라 두 행이 생긴 경우)
    #    같은 (tenant_id, channel_id, od_no, od_seq) 중 최신 created_at만 남김
    op.execute("""
        DELETE FROM samba_order
        WHERE source = 'lotteon'
          AND id IN (
              SELECT id FROM (
                  SELECT id,
                         ROW_NUMBER() OVER (
                             PARTITION BY tenant_id, channel_id, od_no, od_seq
                             ORDER BY created_at DESC
                         ) AS rn
                  FROM samba_order
                  WHERE source = 'lotteon'
                    AND od_no IS NOT NULL
                    AND od_seq IS NOT NULL
              ) ranked
              WHERE rn > 1
          );
    """)

    # 2. order_number를 od_no_od_seq 형식으로 통일
    #    이미 _ 기준 2개 부분만 있는 것은 건드리지 않음
    op.execute("""
        UPDATE samba_order
        SET order_number = od_no || '_' || od_seq
        WHERE source = 'lotteon'
          AND od_no IS NOT NULL
          AND od_seq IS NOT NULL
          AND order_number != (od_no || '_' || od_seq);
    """)

    # 3. 기존 ix_samba_order_lotteon_line 인덱스 제거 (proc_seq 포함된 구버전)
    op.execute("""
        DROP INDEX IF EXISTS ix_samba_order_lotteon_line;
    """)

    # 4. proc_seq 없는 인덱스로 재생성
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_samba_order_lotteon_line
        ON samba_order (tenant_id, channel_id, od_no, od_seq)
        WHERE source = 'lotteon';
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_samba_order_lotteon_line;")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_samba_order_lotteon_line
        ON samba_order (tenant_id, channel_id, od_no, od_seq, proc_seq)
        WHERE source = 'lotteon';
    """)
