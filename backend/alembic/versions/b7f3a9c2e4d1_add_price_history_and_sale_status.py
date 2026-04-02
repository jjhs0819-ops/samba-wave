"""add_price_history_and_sale_status

Revision ID: b7f3a9c2e4d1
Revises: a3f2b1c4d5e6
Create Date: 2026-03-17 15:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7f3a9c2e4d1"
down_revision: Union[str, Sequence[str], None] = "a3f2b1c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 가격/재고 이력 컬럼 추가
    op.add_column(
        "samba_collected_product",
        sa.Column("price_history", sa.JSON(), nullable=True),
    )
    # 판매 상태 컬럼 추가 (in_stock / sold_out / preorder)
    op.add_column(
        "samba_collected_product",
        sa.Column("sale_status", sa.Text(), server_default="in_stock", nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("samba_collected_product", "sale_status")
    op.drop_column("samba_collected_product", "price_history")
