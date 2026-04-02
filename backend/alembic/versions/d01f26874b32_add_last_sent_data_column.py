"""add_last_sent_data_column

Revision ID: d01f26874b32
Revises: 8355b1006c94
Create Date: 2026-03-22 21:31:39.914120

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d01f26874b32"
down_revision: Union[str, Sequence[str], None] = "8355b1006c94"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "samba_collected_product", sa.Column("last_sent_data", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("samba_collected_product", "last_sent_data")
