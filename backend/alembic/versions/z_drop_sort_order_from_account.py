"""SambaMarketAccount에서 sort_order 컬럼 제거

Revision ID: z_drop_sort_order_001
Revises: z_add_source_brand_001
Create Date: 2026-04-09

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "z_drop_sort_order_001"
down_revision: Union[str, Sequence[str]] = "z_add_source_brand_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF EXISTS — 프로덕션 DB에서 이미 제거된 경우 안전
    op.execute("ALTER TABLE samba_market_account DROP COLUMN IF EXISTS sort_order")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE samba_market_account "
        "ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0"
    )
