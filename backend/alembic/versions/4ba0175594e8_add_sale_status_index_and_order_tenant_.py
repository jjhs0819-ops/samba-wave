"""add sale_status index and order tenant_paid_at index

Revision ID: 4ba0175594e8
Revises: 37fd18b908e6
Create Date: 2026-05-06 10:06:01.377468

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "4ba0175594e8"
down_revision: Union[str, Sequence[str], None] = "37fd18b908e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_scp_sale_status"
        " ON samba_collected_product (sale_status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_samba_order_tenant_paid_at"
        " ON samba_order (tenant_id, paid_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_scp_sale_status")
    op.execute("DROP INDEX IF EXISTS ix_samba_order_tenant_paid_at")
