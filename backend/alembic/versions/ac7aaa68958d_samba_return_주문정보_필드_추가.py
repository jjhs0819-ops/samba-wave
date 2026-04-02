"""samba_return 주문정보 필드 추가

Revision ID: ac7aaa68958d
Revises: eb5f99681f74
Create Date: 2026-03-26 08:28:38.635322

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "ac7aaa68958d"
down_revision: Union[str, Sequence[str], None] = "eb5f99681f74"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("samba_return", sa.Column("order_number", sa.Text(), nullable=True))
    op.add_column("samba_return", sa.Column("product_name", sa.Text(), nullable=True))
    op.add_column("samba_return", sa.Column("customer_name", sa.Text(), nullable=True))
    op.add_column("samba_return", sa.Column("business_name", sa.Text(), nullable=True))
    op.add_column("samba_return", sa.Column("market", sa.Text(), nullable=True))
    op.add_column(
        "samba_return",
        sa.Column("confirmed", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "samba_return",
        sa.Column("order_date", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "samba_return", sa.Column("settlement_amount", sa.Float(), nullable=True)
    )
    op.add_column(
        "samba_return", sa.Column("recovery_amount", sa.Float(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("samba_return", "recovery_amount")
    op.drop_column("samba_return", "settlement_amount")
    op.drop_column("samba_return", "order_date")
    op.drop_column("samba_return", "confirmed")
    op.drop_column("samba_return", "market")
    op.drop_column("samba_return", "business_name")
    op.drop_column("samba_return", "customer_name")
    op.drop_column("samba_return", "product_name")
    op.drop_column("samba_return", "order_number")
