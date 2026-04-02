"""samba_return market_order_status

Revision ID: 45f742d91792
Revises: a98cdfc561f2
Create Date: 2026-03-26 09:10:24.912261

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "45f742d91792"
down_revision: Union[str, Sequence[str], None] = "a98cdfc561f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "samba_return", sa.Column("market_order_status", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("samba_return", "market_order_status")
