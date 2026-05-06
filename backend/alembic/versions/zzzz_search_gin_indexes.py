"""주문·상품 검색 GIN trigram 인덱스 추가

12만 상품 수집 후 LIKE '%xxx%' 전체 스캔 이슈 해결.
- samba_order: customer_name, product_name, order_number GIN trgm 인덱스
- samba_product: name GIN trgm 인덱스

Revision ID: zzzz_search_gin_indexes
Revises: zzz_registered_accounts_jsonb
Create Date: 2026-05-06 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "zzzz_search_gin_indexes"
down_revision: Union[str, Sequence[str], None] = "zzz_registered_accounts_jsonb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # samba_order 검색 필드 GIN 인덱스
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_samba_order_customer_name_trgm
        ON samba_order USING gin (customer_name gin_trgm_ops)
        WHERE customer_name IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_samba_order_product_name_trgm
        ON samba_order USING gin (product_name gin_trgm_ops)
        WHERE product_name IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_samba_order_order_number_trgm
        ON samba_order USING gin (order_number gin_trgm_ops)
        WHERE order_number IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_samba_order_customer_phone_trgm
        ON samba_order USING gin (customer_phone gin_trgm_ops)
        WHERE customer_phone IS NOT NULL
    """)

    # samba_product name 검색 GIN 인덱스
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_samba_product_name_trgm
        ON samba_product USING gin (name gin_trgm_ops)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_samba_product_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_samba_order_customer_phone_trgm")
    op.execute("DROP INDEX IF EXISTS ix_samba_order_order_number_trgm")
    op.execute("DROP INDEX IF EXISTS ix_samba_order_product_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_samba_order_customer_name_trgm")
