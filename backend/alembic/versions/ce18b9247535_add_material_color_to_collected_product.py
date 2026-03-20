"""add_material_color_to_collected_product

Revision ID: ce18b9247535
Revises: n2o3p4q5r6s7
Create Date: 2026-03-19 15:33:41.728843

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ce18b9247535'
down_revision: Union[str, Sequence[str], None] = 'n2o3p4q5r6s7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('samba_collected_product', sa.Column('material', sa.Text(), nullable=True))
    op.add_column('samba_collected_product', sa.Column('color', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('samba_collected_product', 'color')
    op.drop_column('samba_collected_product', 'material')
