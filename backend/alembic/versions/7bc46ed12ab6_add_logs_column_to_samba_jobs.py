"""add logs column to samba_jobs

Revision ID: 7bc46ed12ab6
Revises: 873871a20399
Create Date: 2026-04-18 12:06:15.540259

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "7bc46ed12ab6"
down_revision: Union[str, Sequence[str], None] = "873871a20399"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = set(inspector.get_table_names(schema="public"))

    if "samba_sns_auto_config" not in existing:
        op.create_table(
            "samba_sns_auto_config",
            sa.Column(
                "id", sqlmodel.sql.sqltypes.AutoString(length=30), nullable=False
            ),
            sa.Column("tenant_id", sa.String(), nullable=True),
            sa.Column("wp_site_id", sa.String(length=30), nullable=False),
            sa.Column(
                "interval_minutes", sa.Integer(), server_default="20", nullable=False
            ),
            sa.Column(
                "max_daily_posts", sa.Integer(), server_default="150", nullable=False
            ),
            sa.Column(
                "is_running", sa.Boolean(), server_default="false", nullable=False
            ),
            sa.Column(
                "language", sa.String(length=5), server_default="ko", nullable=False
            ),
            sa.Column(
                "include_product_banner",
                sa.Boolean(),
                server_default="true",
                nullable=False,
            ),
            sa.Column("product_banner_html", sa.Text(), nullable=True),
            sa.Column("today_count", sa.Integer(), server_default="0", nullable=False),
            sa.Column("last_posted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_samba_sns_auto_config_tenant_id"),
            "samba_sns_auto_config",
            ["tenant_id"],
            unique=False,
        )

    if "samba_sns_keyword_group" not in existing:
        op.create_table(
            "samba_sns_keyword_group",
            sa.Column(
                "id", sqlmodel.sql.sqltypes.AutoString(length=30), nullable=False
            ),
            sa.Column("tenant_id", sa.String(), nullable=True),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("category", sa.String(length=50), nullable=False),
            sa.Column("keywords", sa.JSON(), nullable=False),
            sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_samba_sns_keyword_group_tenant_id"),
            "samba_sns_keyword_group",
            ["tenant_id"],
            unique=False,
        )

    if "samba_sns_post" not in existing:
        op.create_table(
            "samba_sns_post",
            sa.Column(
                "id", sqlmodel.sql.sqltypes.AutoString(length=30), nullable=False
            ),
            sa.Column("tenant_id", sa.String(), nullable=True),
            sa.Column("wp_site_id", sa.String(length=30), nullable=True),
            sa.Column("wp_post_id", sa.Integer(), nullable=True),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("content", sa.Text(), nullable=True),
            sa.Column("category", sa.String(length=100), nullable=True),
            sa.Column("keyword", sa.String(length=200), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column(
                "status", sa.String(length=20), server_default="draft", nullable=False
            ),
            sa.Column(
                "language", sa.String(length=5), server_default="ko", nullable=False
            ),
            sa.Column("product_ids", sa.JSON(), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_samba_sns_post_tenant_id"),
            "samba_sns_post",
            ["tenant_id"],
            unique=False,
        )

    if "samba_tenants" not in existing:
        op.create_table(
            "samba_tenants",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("owner_user_id", sa.String(), nullable=False),
            sa.Column("plan", sa.String(), nullable=False),
            sa.Column("limits", sa.JSON(), nullable=True),
            sa.Column("subscription_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("subscription_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "autotune_enabled", sa.Boolean(), server_default="false", nullable=False
            ),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if "samba_wp_site" not in existing:
        op.create_table(
            "samba_wp_site",
            sa.Column(
                "id", sqlmodel.sql.sqltypes.AutoString(length=30), nullable=False
            ),
            sa.Column("tenant_id", sa.String(), nullable=True),
            sa.Column("site_url", sa.Text(), nullable=False),
            sa.Column("username", sa.String(length=100), nullable=False),
            sa.Column("app_password", sa.Text(), nullable=False),
            sa.Column("site_name", sa.String(length=200), nullable=True),
            sa.Column(
                "status", sa.String(length=20), server_default="active", nullable=False
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_samba_wp_site_tenant_id"),
            "samba_wp_site",
            ["tenant_id"],
            unique=False,
        )

    # IF NOT EXISTS로 기존 컬럼 중복 추가 방지
    op.execute("ALTER TABLE samba_jobs ADD COLUMN IF NOT EXISTS logs JSON")


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("samba_jobs", "logs")
    op.drop_index(op.f("ix_samba_wp_site_tenant_id"), table_name="samba_wp_site")
    op.drop_table("samba_wp_site")
    op.drop_table("samba_tenants")
    op.drop_index(op.f("ix_samba_sns_post_tenant_id"), table_name="samba_sns_post")
    op.drop_table("samba_sns_post")
    op.drop_index(
        op.f("ix_samba_sns_keyword_group_tenant_id"),
        table_name="samba_sns_keyword_group",
    )
    op.drop_table("samba_sns_keyword_group")
    op.drop_index(
        op.f("ix_samba_sns_auto_config_tenant_id"), table_name="samba_sns_auto_config"
    )
    op.drop_table("samba_sns_auto_config")
    # ### end Alembic commands ###
