"""samba_order 11번가 라인키 컬럼 추가 (ord_prd_seq)

Revision ID: z_elevenst_ord_prd_seq
Revises: 202605011300_fix_lt_exchg
Create Date: 2026-05-01 14:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "z_elevenst_ord_prd_seq"
down_revision: Union[str, None] = "202605011300_fix_lt_exchg"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 11번가 판매불가처리/취소승인 API 필수 파라미터 ordPrdSeq 저장용
    # IF NOT EXISTS로 재실행 안전
    op.execute("ALTER TABLE samba_order ADD COLUMN IF NOT EXISTS ord_prd_seq TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE samba_order DROP COLUMN IF EXISTS ord_prd_seq")
