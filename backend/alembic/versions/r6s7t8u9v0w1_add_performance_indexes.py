"""상품관리 페이지 성능 개선 인덱스 추가

- created_at DESC 인덱스 (정렬 최적화)
- (source_site, created_at DESC) 복합 인덱스 (필터+정렬 커버링)
- updated_at DESC 인덱스 (업데이트순 정렬)
- name gin_trgm 인덱스 (ILIKE 검색 최적화)
- brand gin_trgm 인덱스 (ILIKE 검색 최적화)

Revision ID: r6s7t8u9v0w1
Revises: q5r6s7t8u9v0
Create Date: 2026-03-27 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'r6s7t8u9v0w1'
down_revision: Union[str, Sequence[str], None] = 'q5r6s7t8u9v0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """성능 인덱스 추가."""
    # pg_trgm 확장 활성화 (ILIKE 인덱스용)
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # 정렬용 인덱스
    op.create_index(
        'ix_scp_created_at_desc',
        'samba_collected_product',
        ['created_at'],
        postgresql_using='btree',
        postgresql_ops={'created_at': 'DESC'},
    )
    op.create_index(
        'ix_scp_updated_at_desc',
        'samba_collected_product',
        ['updated_at'],
        postgresql_using='btree',
        postgresql_ops={'updated_at': 'DESC'},
    )

    # 소싱처 + 생성일 복합 인덱스 (필터+정렬 커버링)
    op.create_index(
        'ix_scp_source_site_created_at',
        'samba_collected_product',
        ['source_site', 'created_at'],
        postgresql_using='btree',
        postgresql_ops={'created_at': 'DESC'},
    )

    # 상품명 trigram GIN 인덱스 (ILIKE 검색 최적화)
    op.execute(
        "CREATE INDEX ix_scp_name_trgm ON samba_collected_product "
        "USING gin (name gin_trgm_ops)"
    )

    # 브랜드 trigram GIN 인덱스
    op.execute(
        "CREATE INDEX ix_scp_brand_trgm ON samba_collected_product "
        "USING gin (brand gin_trgm_ops)"
    )

    # 주문 테이블 product_id 인덱스 (has_orders 서브쿼리 최적화, 이미 존재할 수 있음)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_samba_order_product_id ON samba_order (product_id)"
    )


def downgrade() -> None:
    """성능 인덱스 제거."""
    op.drop_index('ix_samba_order_product_id', table_name='samba_order')
    op.execute("DROP INDEX IF EXISTS ix_scp_brand_trgm")
    op.execute("DROP INDEX IF EXISTS ix_scp_name_trgm")
    op.drop_index('ix_scp_source_site_created_at', table_name='samba_collected_product')
    op.drop_index('ix_scp_updated_at_desc', table_name='samba_collected_product')
    op.drop_index('ix_scp_created_at_desc', table_name='samba_collected_product')
