"""samba_return completion_detail

Revision ID: f71132fc5b81
Revises: 0b6587eabb44
Create Date: 2026-03-26 09:14:47.695776

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f71132fc5b81"
down_revision: Union[str, Sequence[str], None] = "0b6587eabb44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "samba_return", sa.Column("completion_detail", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("samba_return", "completion_detail")
    # ### end Alembic commands ###
