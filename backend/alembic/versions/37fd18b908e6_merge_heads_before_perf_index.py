"""merge heads before perf index

Revision ID: 37fd18b908e6
Revises: z_add_sourcing_recipes, z_add_tetris_assignment
Create Date: 2026-05-06 10:05:25.475808

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "37fd18b908e6"
down_revision: Union[str, Sequence[str], None] = (
    "z_add_sourcing_recipes",
    "z_add_tetris_assignment",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
