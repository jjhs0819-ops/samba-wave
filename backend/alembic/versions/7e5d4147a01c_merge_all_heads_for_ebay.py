"""merge_all_heads_for_ebay

Revision ID: 7e5d4147a01c
Revises: z_order_cpid_001, z_add_samba_ebay_mapping
Create Date: 2026-04-12 18:21:53.467692

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "7e5d4147a01c"
down_revision: Union[str, Sequence[str], None] = (
    "z_order_cpid_001",
    "z_add_samba_ebay_mapping",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
