"""samba_order.claim_order_number 추가 — GS 등 반품 새 주문번호 표시용

Revision ID: add_claim_order_no_0701
Revises: at_transmit_scalar_idx_0622
Create Date: 2026-07-01

GS는 반품/교환에 새 주문번호를 부여하고 원주문번호는 orgOrdNo로 준다.
원주문(order_number)은 유지하고 반품이 받은 새 번호를 claim_order_number에 보관해
주문 화면에 "원주문번호 반품 반품번호"로 함께 표시한다.
"""

from alembic import op

revision = "add_claim_order_no_0701"
down_revision = "at_transmit_scalar_idx_0622"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE samba_order ADD COLUMN IF NOT EXISTS claim_order_number TEXT"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE samba_order DROP COLUMN IF EXISTS claim_order_number")
