"""samba_collected_product.resell_matches 컬럼 추가 (KREAM/POIZON/StockX 매칭 기록)

Revision ID: resell_matches_0616
Revises: scmetrics_0616
Create Date: 2026-06-16

hot 테이블(samba_collected_product) — 데드락 방지 위해 컬럼 존재 시 ALTER 스킵.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "resell_matches_0616"
down_revision = "scmetrics_0616"
branch_labels = None
depends_on = None

_TABLE = "samba_collected_product"
_COL = "resell_matches"


def _column_exists(conn) -> bool:
    row = conn.execute(
        sa.text(
            """SELECT 1 FROM information_schema.columns
               WHERE table_name = :t AND column_name = :c"""
        ),
        {"t": _TABLE, "c": _COL},
    ).first()
    return row is not None


def upgrade() -> None:
    conn = op.get_bind()
    # hot 테이블: 이미 컬럼 있으면 ALTER 자체 스킵(AccessExclusiveLock 데드락 방지)
    if _column_exists(conn):
        return
    op.add_column(_TABLE, sa.Column(_COL, JSONB(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    if not _column_exists(conn):
        return
    op.drop_column(_TABLE, _COL)
