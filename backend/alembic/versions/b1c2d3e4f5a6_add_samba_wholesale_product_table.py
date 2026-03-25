"""samba_wholesale_product 테이블 생성

Revision ID: b1c2d3e4f5a6
Revises: 2a3ab66db7a7
Create Date: 2026-03-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = '2a3ab66db7a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'samba_wholesale_product',
        sa.Column('id', sa.String(length=30), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=True),
        sa.Column('source_mall', sa.String(length=50), nullable=False),
        sa.Column('product_id', sa.String(length=100), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('price', sa.Integer(), nullable=False),
        sa.Column('retail_price', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(length=200), nullable=True),
        sa.Column('image_url', sa.Text(), nullable=True),
        sa.Column('detail_url', sa.Text(), nullable=True),
        sa.Column('options', sa.JSON(), nullable=True),
        sa.Column('stock_status', sa.String(length=20), server_default='in_stock', nullable=False),
        sa.Column('collected_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    # 인덱스 생성
    op.create_index(op.f('ix_samba_wholesale_product_tenant_id'), 'samba_wholesale_product', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_samba_wholesale_product_source_mall'), 'samba_wholesale_product', ['source_mall'], unique=False)
    op.create_index(op.f('ix_samba_wholesale_product_product_id'), 'samba_wholesale_product', ['product_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_samba_wholesale_product_product_id'), table_name='samba_wholesale_product')
    op.drop_index(op.f('ix_samba_wholesale_product_source_mall'), table_name='samba_wholesale_product')
    op.drop_index(op.f('ix_samba_wholesale_product_tenant_id'), table_name='samba_wholesale_product')
    op.drop_table('samba_wholesale_product')
