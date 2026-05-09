"""samba_order.orderer_name 컬럼 추가 — 주문자명/수취인명 분리.

롯데ON 주문에서 주문자(odrNm)와 수취인(dvpCustNm)이 다를 수 있음.
기존 customer_name은 수취인명으로 유지하고, orderer_name을 신규 추가.

Revision ID: zzzzzzzzzzz_add_orderer_name_to_samba_order
Revises: zzzzzzzzzz_add_samba_extension_key
Create Date: 2026-05-09
"""

from alembic import op


revision = "zzzzzzzzzzz_add_orderer_name_to_samba_order"
down_revision = "zzzzzzzzzz_add_samba_extension_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE samba_order ADD COLUMN IF NOT EXISTS orderer_name TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE samba_order DROP COLUMN IF EXISTS orderer_name")
