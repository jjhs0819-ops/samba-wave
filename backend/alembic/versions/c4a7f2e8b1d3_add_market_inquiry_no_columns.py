"""add_market_inquiry_no_columns

Revision ID: c4a7f2e8b1d3
Revises: 823ecbf7765b
Create Date: 2026-03-25 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4a7f2e8b1d3'
down_revision: Union[str, Sequence[str], None] = '823ecbf7765b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('samba_cs_inquiry', sa.Column('market_inquiry_no', sa.Text(), nullable=True))
    op.add_column('samba_cs_inquiry', sa.Column('market_answer_no', sa.Text(), nullable=True))
    op.create_index(
        op.f('ix_samba_cs_inquiry_market_inquiry_no'),
        'samba_cs_inquiry',
        ['market_inquiry_no'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_samba_cs_inquiry_market_inquiry_no'), table_name='samba_cs_inquiry')
    op.drop_column('samba_cs_inquiry', 'market_answer_no')
    op.drop_column('samba_cs_inquiry', 'market_inquiry_no')
