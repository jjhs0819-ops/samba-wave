"""add_logs_column_to_samba_jobs

Revision ID: 540a56de92dd
Revises: 7bc46ed12ab6
Create Date: 2026-04-18 15:03:12.010843

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '540a56de92dd'
down_revision: Union[str, Sequence[str], None] = '7bc46ed12ab6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE samba_jobs ADD COLUMN IF NOT EXISTS logs JSON")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE samba_jobs DROP COLUMN IF EXISTS logs")
