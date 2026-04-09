"""merge_all_heads_for_autotune_fix

Revision ID: ad3d158aae34
Revises: 8c61d687b4ab, z_rexmonde_001
Create Date: 2026-04-09 15:00:09.765646

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "ad3d158aae34"
down_revision: Union[str, Sequence[str], None] = ("8c61d687b4ab", "z_rexmonde_001")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
