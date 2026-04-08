"""merge_coupang_and_sourcing_order_heads

Revision ID: b3786b6834dc
Revises: d985fc142e4a, z3a4b5c6d7e8
Create Date: 2026-04-03 10:04:23.426496

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "b3786b6834dc"
down_revision: Union[str, Sequence[str], None] = ("d985fc142e4a", "z3a4b5c6d7e8")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
