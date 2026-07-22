"""samba_brand_restriction 테이블 추가 — 소명/지재권 브랜드 관리

Revision ID: add_brand_restriction_0723
Revises: add_order_ship_by_0715
Create Date: 2026-07-23

쿠팡 등 마켓은 유통경로 소명 없이 특정 브랜드를 팔면 판매정지를 건다.
업로드 직전에 차단하기 위한 브랜드 판정 테이블.

UNIQUE 인덱스는 **NULLS NOT DISTINCT** 로 만든다. 브랜드 제한은 전역
(tenant_id=NULL)으로 적재되는데, Postgres 기본 UNIQUE 는 NULL 을 서로 다른
값으로 보기 때문에 그냥 걸면 같은 브랜드가 여러 행으로 들어간다.
(같은 사고 선례: fix_order_unique_nulls_not_distinct_0703)
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "add_brand_restriction_0723"
down_revision = "add_order_ship_by_0715"
branch_labels = None
depends_on = None

TABLE = "samba_brand_restriction"


def _has_table(table: str) -> bool:
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
        {"t": table},
    ).fetchone()
    return row is not None


def upgrade() -> None:
    if _has_table(TABLE):
        return

    op.create_table(
        TABLE,
        sa.Column("id", sa.String(length=30), primary_key=True),
        # 브랜드 제한은 전역(NULL)이 기본 — 소명 여부는 판매 계정과 무관하다.
        # 테넌트 지정 행은 그 위에 얹는 예외로만 쓴다.
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("brand", sa.Text(), nullable=False),
        sa.Column("brand_key", sa.Text(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("soomyeong", sa.Text(), nullable=True),
        sa.Column("ipr", sa.Text(), nullable=True),
        sa.Column("markets", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("coupang_uid_required", sa.Boolean(), nullable=True),
        sa.Column("coupang_matched", sa.Boolean(), nullable=True),
        sa.Column("coupang_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
        sa.Column(
            "source_detail", postgresql.JSON(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_brand_restriction_tenant", TABLE, ["tenant_id"])
    op.create_index("ix_brand_restriction_verdict", TABLE, ["verdict"])
    op.create_index("ix_brand_restriction_source", TABLE, ["source"])
    op.execute(
        "CREATE UNIQUE INDEX ux_brand_restriction_key "
        f"ON {TABLE} (tenant_id, brand_key) NULLS NOT DISTINCT"
    )


def downgrade() -> None:
    if not _has_table(TABLE):
        return
    op.execute("DROP INDEX IF EXISTS ux_brand_restriction_key")
    op.drop_index("ix_brand_restriction_source", table_name=TABLE)
    op.drop_index("ix_brand_restriction_verdict", table_name=TABLE)
    op.drop_index("ix_brand_restriction_tenant", table_name=TABLE)
    op.drop_table(TABLE)
