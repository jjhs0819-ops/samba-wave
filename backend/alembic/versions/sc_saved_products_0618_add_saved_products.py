"""store_care_saved_products 테이블 추가 (가구매 저장 상품 — 이름→URL 북마크)

Revision ID: sc_saved_products_0618
Revises: resell_matches_0616
Create Date: 2026-06-18

가구매 폼에서 자주 쓰는 상품 URL을 이름으로 저장/불러오기 (마켓별, 테넌트별).
"""

from alembic import op
import sqlalchemy as sa

revision = "sc_saved_products_0618"
down_revision = "resell_matches_0616"
branch_labels = None
depends_on = None

_TABLE = "store_care_saved_products"


def _table_exists(conn) -> bool:
    row = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
        {"t": _TABLE},
    ).first()
    return row is not None


def upgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn):  # 재실행 안전 (이미 있으면 스킵)
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("market_type", sa.String(length=30), nullable=False),
        sa.Column("product_url", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_store_care_saved_products_tenant_id",
        _TABLE,
        ["tenant_id"],
    )


def downgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn):
        return
    op.drop_index("ix_store_care_saved_products_tenant_id", table_name=_TABLE)
    op.drop_table(_TABLE)
