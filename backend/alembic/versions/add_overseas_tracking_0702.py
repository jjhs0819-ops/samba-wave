"""add overseas shipping columns to samba_order — 크림 해외택배사/해외송장 (SNKRDUNK 해외매입)

Revision ID: add_overseas_tracking_0702
Revises: add_cp_memo_0701
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "add_overseas_tracking_0702"
down_revision = "add_cp_memo_0701"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "samba_order",
        sa.Column("overseas_shipping_company", sa.Text(), nullable=True),
    )
    op.add_column(
        "samba_order",
        sa.Column("overseas_tracking_number", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("samba_order", "overseas_tracking_number")
    op.drop_column("samba_order", "overseas_shipping_company")
