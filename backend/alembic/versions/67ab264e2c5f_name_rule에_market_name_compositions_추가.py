"""name_rule에 market_name_compositions 추가

Revision ID: 67ab264e2c5f
Revises: w2b3c4d5e6f7
Create Date: 2026-03-30 17:56:31.403391

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '67ab264e2c5f'
down_revision: Union[str, Sequence[str], None] = 'w2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('samba_name_rule', sa.Column('market_name_compositions', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('samba_name_rule', 'market_name_compositions')
