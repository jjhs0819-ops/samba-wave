"""add seo_keywords column

Revision ID: 1fd6c0f682e9
Revises: d589705d6476
Create Date: 2026-03-22 01:31:38.347936

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1fd6c0f682e9'
down_revision: Union[str, Sequence[str], None] = 'd589705d6476'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('samba_collected_product', sa.Column('seo_keywords', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('samba_collected_product', 'seo_keywords')
