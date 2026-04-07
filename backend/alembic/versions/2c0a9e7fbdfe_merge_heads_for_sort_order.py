"""merge_heads_for_sort_order

Revision ID: 2c0a9e7fbdfe
Revises: 5a2adcea62c2, z_add_created_by, z_job_attempt_001
Create Date: 2026-04-06 16:38:17.361920

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "2c0a9e7fbdfe"
down_revision: Union[str, Sequence[str], None] = (
    "5a2adcea62c2",
    "z_add_created_by",
    "z_job_attempt_001",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
