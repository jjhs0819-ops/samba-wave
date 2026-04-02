"""add coupang_main_image column

Revision ID: d985fc142e4a
Revises: 67ab264e2c5f
Create Date: 2026-03-31 22:52:25.935538

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d985fc142e4a"
down_revision: Union[str, Sequence[str], None] = "67ab264e2c5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "samba_collected_product",
        sa.Column("coupang_main_image", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("samba_collected_product", "coupang_main_image")
