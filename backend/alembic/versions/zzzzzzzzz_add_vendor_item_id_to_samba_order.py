"""samba_order vendor_item_id 컬럼 추가 — 쿠팡 송장업로드 API 필수 파라미터

Revision ID: zzzzzzzzz_vendor_item_id
Revises: zzzzzzzz_cs_inquiry_missing_columns
Create Date: 2026-05-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "zzzzzzzzz_vendor_item_id"
down_revision: Union[str, Sequence[str], None] = "zzzzzzzz_cs_inquiry_missing_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _col_exists(conn, table: str, col: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": col},
    ).fetchone()
    return result is not None


def upgrade() -> None:
    # ALTER 시점 AccessExclusiveLock 회피 — 컬럼 존재 시 스킵.
    conn = op.get_bind()
    if not _col_exists(conn, "samba_order", "vendor_item_id"):
        op.execute(
            "ALTER TABLE samba_order ADD COLUMN IF NOT EXISTS vendor_item_id TEXT"
        )


def downgrade() -> None:
    op.execute("ALTER TABLE samba_order DROP COLUMN IF EXISTS vendor_item_id")
