"""samba_collected_product에 source_url, extra_data 컬럼 추가

- source_url: 소싱처 원문 상품 페이지 URL (프록시 sourceUrl 저장)
- extra_data: 프록시에서 보내는 미매핑 필드 자동 보존용 JSON
- 기존 데이터 source_url 역생성 (source_site + site_product_id 기반)

Revision ID: s7t8u9v0w1x2
Revises: r6s7t8u9v0w1
Create Date: 2026-03-27 15:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "s7t8u9v0w1x2"
down_revision: Union[str, Sequence[str], None] = "r6s7t8u9v0w1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 기존 데이터 source_url 역생성용 URL 템플릿
_SOURCE_URL_TEMPLATES = {
    "MUSINSA": "https://www.musinsa.com/products/{id}",
    "KREAM": "https://kream.co.kr/products/{id}",
    "LOTTEON": "https://www.lotteon.com/product/{id}",
    "SSG": "https://www.ssg.com/item/itemView.ssg?itemId={id}",
    "ABCmart": "https://abcmart.a-rt.com/product/detail?goodsId={id}",
    "FashionPlus": "https://www.fashionplus.co.kr/goods/{id}",
    "Nike": "https://www.nike.com/kr/t/{id}",
    "Adidas": "https://www.adidas.co.kr/{id}",
    "GMarket": "https://item.gmarket.co.kr/Item?goodscode={id}",
    "SmartStore": "https://smartstore.naver.com/products/{id}",
}


def upgrade() -> None:
    # 1. 컬럼 추가
    op.add_column(
        "samba_collected_product", sa.Column("source_url", sa.Text(), nullable=True)
    )
    op.add_column(
        "samba_collected_product", sa.Column("extra_data", sa.JSON(), nullable=True)
    )

    # 2. 기존 데이터 source_url 역생성
    conn = op.get_bind()
    for site, template in _SOURCE_URL_TEMPLATES.items():
        url_expr = template.replace("{id}", "' || site_product_id || '")
        conn.execute(
            sa.text(
                f"UPDATE samba_collected_product "
                f"SET source_url = '{url_expr}' "
                f"WHERE source_site = :site "
                f"AND site_product_id IS NOT NULL "
                f"AND (source_url IS NULL OR source_url = '')"
            ),
            {"site": site},
        )


def downgrade() -> None:
    op.drop_column("samba_collected_product", "extra_data")
    op.drop_column("samba_collected_product", "source_url")
