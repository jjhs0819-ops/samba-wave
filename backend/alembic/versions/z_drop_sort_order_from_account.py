"""SambaMarketAccount에서 sort_order 컬럼 제거

Revision ID: z_drop_sort_order_001
Revises: z_add_source_brand_001
Create Date: 2026-04-09

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "z_drop_sort_order_001"
down_revision: Union[str, Sequence[str]] = "z_add_source_brand_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("samba_market_account", "sort_order")


def downgrade() -> None:
    op.add_column(
        "samba_market_account",
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
    )
