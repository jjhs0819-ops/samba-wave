"""반품탭 마감(종결) + 자동조회 쿨다운 컬럼 추가 (samba_return)

Revision ID: return_closing_01
Revises: order_price_scan_01
Create Date: 2026-09-03

[T7][T8] 반품교환탭 마감 개념 도입:
  samba_return.closed_at        — 마감 시각 (NULL = 미마감. 마감행은 목록 기본 제외)
  samba_return.closed_by        — 'manual'(사장님 버튼) | 'auto'(향후 자동 마감)
  samba_return.auto_checked_at  — 회수 자동조회가 마지막으로 이 행을 본 시각 (쿨다운용)

samba_return 은 hot 테이블은 아니지만 기존 마이그레이션 관례(_exists 사전확인 →
없을 때만 ADD COLUMN IF NOT EXISTS)를 그대로 따른다. downgrade 는 운영 규칙상 안 한다.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "return_closing_01"
down_revision: Union[str, Sequence[str], None] = "order_price_scan_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "samba_return"


def upgrade() -> None:
    # 컬럼이 이미 있으면 ALTER 자체를 스킵 — AccessExclusiveLock 회피 패턴
    # (zzz_return_collect_tracking.py 의 _exists 사전확인 관례 준수)
    from sqlalchemy import text as _sa_text

    conn = op.get_bind()

    def _exists(table: str, col: str) -> bool:
        r = conn.execute(
            _sa_text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name=:t AND column_name=:c"
            ),
            {"t": table, "c": col},
        ).first()
        return r is not None

    if not _exists(_TABLE, "closed_at"):
        op.execute(
            f"ALTER TABLE {_TABLE} ADD COLUMN IF NOT EXISTS "
            "closed_at TIMESTAMP WITH TIME ZONE"
        )
    if not _exists(_TABLE, "closed_by"):
        op.execute(
            f"ALTER TABLE {_TABLE} ADD COLUMN IF NOT EXISTS closed_by TEXT"
        )
    if not _exists(_TABLE, "auto_checked_at"):
        op.execute(
            f"ALTER TABLE {_TABLE} ADD COLUMN IF NOT EXISTS "
            "auto_checked_at TIMESTAMP WITH TIME ZONE"
        )


def downgrade() -> None:
    # 운영 규칙상 downgrade 하지 않는다
    pass
