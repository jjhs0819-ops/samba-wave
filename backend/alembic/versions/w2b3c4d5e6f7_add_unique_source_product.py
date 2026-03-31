"""소싱처+상품ID 유니크 인덱스 추가 (동시 수집 중복 방지)"""
from typing import Sequence, Union
from alembic import op

revision: str = 'w2b3c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = 'v1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # 기존 중복 데이터 정리: 같은 source_site+site_product_id 중 최신 1건만 유지
    op.execute("""
        DELETE FROM samba_collected_product
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY source_site, site_product_id
                           ORDER BY created_at DESC
                       ) AS rn
                FROM samba_collected_product
                WHERE site_product_id IS NOT NULL
            ) sub
            WHERE rn > 1
        )
    """)
    op.create_index(
        'uq_scp_source_product',
        'samba_collected_product',
        ['source_site', 'site_product_id'],
        unique=True,
    )

def downgrade() -> None:
    op.drop_index('uq_scp_source_product', table_name='samba_collected_product')
