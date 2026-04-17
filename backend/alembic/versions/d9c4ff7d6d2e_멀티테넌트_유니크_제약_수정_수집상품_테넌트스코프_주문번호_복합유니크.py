"""멀티테넌트 유니크 제약 수정: 수집상품 테넌트스코프 + 주문번호 복합유니크

Revision ID: d9c4ff7d6d2e
Revises: 26dd9b23892a
Create Date: 2026-04-16 11:08:08.008997

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = "d9c4ff7d6d2e"
down_revision: Union[str, Sequence[str], None] = "26dd9b23892a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # uq_scp_source_product → uq_scp_tenant_source_product 교체 (tenant_id 포함 복합 유니크)
    # IF EXISTS / IF NOT EXISTS 원시 SQL로 멱등 처리 — 부분 적용 상태에서도 안전
    op.execute("DROP INDEX IF EXISTS uq_scp_source_product")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_scp_tenant_source_product
        ON samba_collected_product (tenant_id, source_site, site_product_id)
        WHERE site_product_id IS NOT NULL
        """
    )
    op.alter_column(
        "samba_detail_template",
        "id",
        existing_type=sa.TEXT(),
        type_=sqlmodel.sql.sqltypes.AutoString(length=30),
        existing_nullable=False,
    )
    op.alter_column(
        "samba_name_rule",
        "id",
        existing_type=sa.TEXT(),
        type_=sqlmodel.sql.sqltypes.AutoString(length=30),
        existing_nullable=False,
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_order_tenant_number
        ON samba_order (tenant_id, order_number)
        """
    )
    op.alter_column(
        "samba_return",
        "tenant_id",
        existing_type=sa.TEXT(),
        type_=sa.String(),
        existing_nullable=True,
    )
    op.alter_column(
        "samba_sourcing_account",
        "id",
        existing_type=sa.TEXT(),
        type_=sqlmodel.sql.sqltypes.AutoString(length=30),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "samba_sourcing_account",
        "id",
        existing_type=sqlmodel.sql.sqltypes.AutoString(length=30),
        type_=sa.TEXT(),
        existing_nullable=False,
    )
    op.alter_column(
        "samba_return",
        "tenant_id",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        existing_nullable=True,
    )
    op.execute("DROP INDEX IF EXISTS uq_order_tenant_number")
    op.alter_column(
        "samba_name_rule",
        "id",
        existing_type=sqlmodel.sql.sqltypes.AutoString(length=30),
        type_=sa.TEXT(),
        existing_nullable=False,
    )
    op.alter_column(
        "samba_detail_template",
        "id",
        existing_type=sqlmodel.sql.sqltypes.AutoString(length=30),
        type_=sa.TEXT(),
        existing_nullable=False,
    )
    op.execute("DROP INDEX IF EXISTS uq_scp_tenant_source_product")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_scp_source_product
        ON samba_collected_product (source_site, site_product_id)
        """
    )
