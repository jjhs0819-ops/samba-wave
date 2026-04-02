"""add_detail_template_and_name_rule

Revision ID: a3f2b1c4d5e6
Revises: 5702896235d6
Create Date: 2026-03-17 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a3f2b1c4d5e6"
down_revision: Union[str, Sequence[str], None] = "5702896235d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 상세페이지 템플릿 테이블 생성
    op.create_table(
        "samba_detail_template",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("main_image_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("top_html", sa.Text(), nullable=True),
        sa.Column("bottom_html", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # 상품/옵션명 규칙 테이블 생성
    op.create_table(
        "samba_name_rule",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("prefix", sa.Text(), nullable=True),
        sa.Column("suffix", sa.Text(), nullable=True),
        sa.Column("replacements", sa.JSON(), nullable=True),
        sa.Column("option_rules", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("samba_name_rule")
    op.drop_table("samba_detail_template")
