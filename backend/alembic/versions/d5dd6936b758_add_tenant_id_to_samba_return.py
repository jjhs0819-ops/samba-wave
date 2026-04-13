"""add_tenant_id_to_samba_return

Revision ID: d5dd6936b758
Revises: 2d79853b73b9
Create Date: 2026-04-13 20:40:07.123722

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d5dd6936b758"
down_revision: Union[str, Sequence[str], None] = "2d79853b73b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """samba_return 테이블에 tenant_id 컬럼 추가 (이미 존재하면 스킵)."""
    conn = op.get_bind()
    # 컬럼 존재 여부 확인 — 이미 있으면 ADD COLUMN 생략
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='samba_return' AND column_name='tenant_id'"
        )
    ).fetchone()
    if not result:
        op.add_column(
            "samba_return",
            sa.Column("tenant_id", sa.String(), nullable=True),
        )

    # 인덱스 존재 여부 확인
    idx_result = conn.execute(
        sa.text(
            "SELECT 1 FROM pg_indexes "
            "WHERE tablename='samba_return' AND indexname='ix_samba_return_tenant_id'"
        )
    ).fetchone()
    if not idx_result:
        op.create_index(
            op.f("ix_samba_return_tenant_id"),
            "samba_return",
            ["tenant_id"],
            unique=False,
        )


def downgrade() -> None:
    """tenant_id 컬럼 롤백."""
    op.drop_index(op.f("ix_samba_return_tenant_id"), table_name="samba_return")
    op.drop_column("samba_return", "tenant_id")
