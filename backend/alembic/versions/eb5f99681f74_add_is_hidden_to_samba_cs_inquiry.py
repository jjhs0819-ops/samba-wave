"""add_is_hidden_to_samba_cs_inquiry

Revision ID: eb5f99681f74
Revises: a60447ddae1d
Create Date: 2026-03-25 19:55:38.300173

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "eb5f99681f74"
down_revision: Union[str, Sequence[str], None] = "a60447ddae1d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "samba_cs_inquiry",
        sa.Column("is_hidden", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("samba_cs_inquiry", "is_hidden")
