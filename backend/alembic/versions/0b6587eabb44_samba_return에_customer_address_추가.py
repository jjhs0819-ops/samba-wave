"""samba_return에 customer_address 추가 + 기존 product_location 일괄 갱신

Revision ID: 0b6587eabb44
Revises: 45f742d91792
Create Date: 2026-03-26 09:14:12.595177

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0b6587eabb44"
down_revision: Union[str, Sequence[str], None] = "45f742d91792"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "samba_return", sa.Column("customer_address", sa.Text(), nullable=True)
    )

    # 기존 반품 레코드에 주문의 customer_address 복사 + product_location 재계산
    op.execute("""
        UPDATE samba_return r
        SET customer_address = o.customer_address
        FROM samba_order o
        WHERE r.order_id = o.id
          AND r.customer_address IS NULL
          AND o.customer_address IS NOT NULL
    """)

    # 광역시/특별시 → 시 형태로 product_location 갱신
    op.execute("""
        UPDATE samba_return
        SET product_location = CASE
            WHEN customer_address ~ '^[가-힣]+광역시'
              THEN regexp_replace(split_part(customer_address, ' ', 1), '광역시$', '시')
            WHEN customer_address ~ '^서울특별시'
              THEN '서울시'
            WHEN customer_address ~ '^세종특별자치시'
              THEN '세종시'
            ELSE product_location
        END
        WHERE customer_address IS NOT NULL
          AND (
            customer_address ~ '^[가-힣]+광역시'
            OR customer_address ~ '^서울특별시'
            OR customer_address ~ '^세종특별자치시'
          )
    """)


def downgrade() -> None:
    op.drop_column("samba_return", "customer_address")
