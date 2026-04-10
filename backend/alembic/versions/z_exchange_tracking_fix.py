"""교환 추적 필드 누락 복구 — samba_return 7개 컬럼 IF NOT EXISTS 추가

Revision ID: z_exchange_fix_001
Revises: z_action_tag_001, z_drop_sort_order_001
Create Date: 2026-04-10

5a2adcea62c2 마이그레이션이 체인에 존재하지만 프로덕션 DB에서
해당 DDL이 실제 적용되지 않은 상태를 복구.
IF NOT EXISTS를 사용하여 이미 존재하는 경우 안전하게 건너뜀.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "z_exchange_fix_001"
down_revision: Union[str, Sequence[str]] = (
    "z_action_tag_001",
    "z_drop_sort_order_001",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    sqls = [
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS clm_req_seq TEXT",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS ord_prd_seq TEXT",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS exchange_retrieval_status TEXT",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS exchange_retrieved_at TIMESTAMPTZ",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS exchange_reship_company TEXT",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS exchange_reship_tracking TEXT",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS exchange_delivered_at TIMESTAMPTZ",
    ]
    for sql in sqls:
        op.execute(sql)


def downgrade() -> None:
    op.execute("ALTER TABLE samba_return DROP COLUMN IF EXISTS exchange_delivered_at")
    op.execute(
        "ALTER TABLE samba_return DROP COLUMN IF EXISTS exchange_reship_tracking"
    )
    op.execute("ALTER TABLE samba_return DROP COLUMN IF EXISTS exchange_reship_company")
    op.execute("ALTER TABLE samba_return DROP COLUMN IF EXISTS exchange_retrieved_at")
    op.execute(
        "ALTER TABLE samba_return DROP COLUMN IF EXISTS exchange_retrieval_status"
    )
    op.execute("ALTER TABLE samba_return DROP COLUMN IF EXISTS ord_prd_seq")
    op.execute("ALTER TABLE samba_return DROP COLUMN IF EXISTS clm_req_seq")
