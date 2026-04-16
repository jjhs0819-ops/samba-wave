"""merge_cafe24_and_multitenancy_heads

Revision ID: 37e835a156d6
Revises: d9c4ff7d6d2e, c4f2407a01
Create Date: 2026-04-16 11:26:37.294830

"""

from typing import Sequence, Union



# revision identifiers, used by Alembic.
revision: str = "37e835a156d6"
down_revision: Union[str, Sequence[str], None] = ("d9c4ff7d6d2e", "c4f2407a01")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
