"""오토튠 누락 컬럼 강제 추가 — IF NOT EXISTS

프로덕션 DB에 monitor_priority, last_refreshed_at, refresh_error_count,
sale_status, price_history, price_changed_at 컬럼이 누락되어
오토튠 tick에서 UndefinedColumn 에러 발생.

z_catchup_001이 이 컬럼들을 포함하지 않았고,
alembic이 m1n2o3p4q5r6을 이미 적용된 것으로 간주하여 건너뜀.

Revision ID: z_fix_autotune_001
Revises: ad3d158aae34
Create Date: 2026-04-09
"""

from typing import Sequence, Union

from alembic import op


revision: str = "z_fix_autotune_001"
down_revision: Union[str, Sequence[str]] = "ad3d158aae34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """오토튠에 필요한 누락 컬럼을 IF NOT EXISTS로 추가."""
    sqls = [
        "ALTER TABLE samba_collected_product ADD COLUMN IF NOT EXISTS monitor_priority TEXT NOT NULL DEFAULT 'cold'",
        "ALTER TABLE samba_collected_product ADD COLUMN IF NOT EXISTS last_refreshed_at TIMESTAMPTZ",
        "ALTER TABLE samba_collected_product ADD COLUMN IF NOT EXISTS refresh_error_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE samba_collected_product ADD COLUMN IF NOT EXISTS sale_status TEXT NOT NULL DEFAULT 'in_stock'",
        "ALTER TABLE samba_collected_product ADD COLUMN IF NOT EXISTS price_history JSON",
        "ALTER TABLE samba_collected_product ADD COLUMN IF NOT EXISTS price_changed_at TIMESTAMPTZ",
    ]
    for sql in sqls:
        op.execute(sql)


def downgrade() -> None:
    pass
