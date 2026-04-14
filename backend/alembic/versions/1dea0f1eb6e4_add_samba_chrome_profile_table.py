"""add_samba_chrome_profile_table

Revision ID: 1dea0f1eb6e4
Revises: d5dd6936b758
Create Date: 2026-04-14 11:11:49.058542

"""

from typing import Sequence, Union

import sqlmodel
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "1dea0f1eb6e4"
down_revision: Union[str, Sequence[str], None] = "d5dd6936b758"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """samba_chrome_profile 테이블 생성 — 확장앱에서 동기화된 크롬 프로필 정보."""
    op.create_table(
        "samba_chrome_profile",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(length=30), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("gaia_id", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_samba_chrome_profile_email"),
        "samba_chrome_profile",
        ["email"],
        unique=False,
    )
    op.create_index(
        op.f("ix_samba_chrome_profile_tenant_id"),
        "samba_chrome_profile",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    """samba_chrome_profile 테이블 삭제."""
    op.drop_index(
        op.f("ix_samba_chrome_profile_tenant_id"), table_name="samba_chrome_profile"
    )
    op.drop_index(
        op.f("ix_samba_chrome_profile_email"), table_name="samba_chrome_profile"
    )
    op.drop_table("samba_chrome_profile")
