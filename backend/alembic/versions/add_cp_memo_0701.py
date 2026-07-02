"""samba_collected_product.memo 추가 — 상품메모(#535)

Revision ID: add_cp_memo_0701
Revises: add_claim_order_no_0701
Create Date: 2026-07-01

상품관리에서 입력한 메모(소싱 특이사항·더 싼 소싱 URL 등)를 보관해
해당 상품의 주문건에서 live-join으로 표시(더망고식).

idempotent:
- samba_collected_product 는 hot 테이블이라 ACCESS EXCLUSIVE 락 경합 발생.
  'IF NOT EXISTS' 도 ALTER 시점에 순간 락을 잡으므로 활성 트랜잭션과 데드락 가능 —
  information_schema 로 컬럼 존재 여부를 먼저 확인하여 있으면 ALTER 자체를 스킵.
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "add_cp_memo_0701"
down_revision: Union[str, Sequence[str], None] = "add_claim_order_no_0701"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = {
        row[0]
        for row in conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'samba_collected_product' "
                "AND column_name = 'memo'"
            )
        )
    }
    if "memo" not in existing:
        op.execute("ALTER TABLE samba_collected_product ADD COLUMN memo TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE samba_collected_product DROP COLUMN IF EXISTS memo")
