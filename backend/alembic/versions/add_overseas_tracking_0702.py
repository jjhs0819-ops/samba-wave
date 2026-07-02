"""add overseas shipping columns to samba_order — 크림 해외택배사/해외송장 (SNKRDUNK 해외매입)

Revision ID: add_overseas_tracking_0702
Revises: add_cp_memo_0701
Create Date: 2026-07-02
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "add_overseas_tracking_0702"
down_revision = "add_cp_memo_0701"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # samba_order 는 hot 테이블 — op.add_column 의 AccessExclusiveLock 이 활성 트랜잭션과
    # 데드락 유발. IF NOT EXISTS 조건으로 컬럼 존재 시 ALTER 자체 스킵.
    conn = op.get_bind()
    rows = conn.execute(
        op.inline_literal(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='samba_order' "
            "AND column_name IN ('overseas_shipping_company','overseas_tracking_number')"
        )
    ).fetchall()
    existing = {r[0] for r in rows}
    if "overseas_shipping_company" not in existing:
        conn.execute(
            op.inline_literal(
                "ALTER TABLE samba_order ADD COLUMN overseas_shipping_company TEXT"
            )
        )
    if "overseas_tracking_number" not in existing:
        conn.execute(
            op.inline_literal(
                "ALTER TABLE samba_order ADD COLUMN overseas_tracking_number TEXT"
            )
        )


def downgrade() -> None:
    op.drop_column("samba_order", "overseas_tracking_number")
    op.drop_column("samba_order", "overseas_shipping_company")
