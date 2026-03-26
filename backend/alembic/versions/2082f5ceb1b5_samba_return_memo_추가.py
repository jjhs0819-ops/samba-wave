"""samba_return memo 추가

Revision ID: 2082f5ceb1b5
Revises: 4c81abda9e0e
Create Date: 2026-03-26 08:54:55.754775

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2082f5ceb1b5'
down_revision: Union[str, Sequence[str], None] = '4c81abda9e0e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('samba_return', sa.Column('memo', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('samba_return', 'memo')
