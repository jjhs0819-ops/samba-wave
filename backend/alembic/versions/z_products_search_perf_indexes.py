"""add product search performance indexes

Revision ID: z_products_search_perf_idx
Revises: c58d77ec580e
Create Date: 2026-04-23 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "z_products_search_perf_idx"
down_revision: Union[str, Sequence[str], None] = "c58d77ec580e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scp_name_nospace_trgm
        ON samba_collected_product
        USING gin ((replace(name, ' ', '')) gin_trgm_ops)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scp_name_en_trgm
        ON samba_collected_product
        USING gin (name_en gin_trgm_ops)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scp_name_en_nospace_trgm
        ON samba_collected_product
        USING gin ((replace(coalesce(name_en, ''), ' ', '')) gin_trgm_ops)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scp_style_code_trgm
        ON samba_collected_product
        USING gin (style_code gin_trgm_ops)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scp_site_product_id_trgm
        ON samba_collected_product
        USING gin (site_product_id gin_trgm_ops)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scp_market_names_trgm
        ON samba_collected_product
        USING gin ((market_names::text) gin_trgm_ops)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scp_tenant_created_at_desc
        ON samba_collected_product (tenant_id, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scp_tenant_source_created_at_desc
        ON samba_collected_product (tenant_id, source_site, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scp_tenant_filter_created_at_desc
        ON samba_collected_product (tenant_id, search_filter_id, created_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_scp_tenant_filter_created_at_desc")
    op.execute("DROP INDEX IF EXISTS ix_scp_tenant_source_created_at_desc")
    op.execute("DROP INDEX IF EXISTS ix_scp_tenant_created_at_desc")
    op.execute("DROP INDEX IF EXISTS ix_scp_market_names_trgm")
    op.execute("DROP INDEX IF EXISTS ix_scp_site_product_id_trgm")
    op.execute("DROP INDEX IF EXISTS ix_scp_style_code_trgm")
    op.execute("DROP INDEX IF EXISTS ix_scp_name_en_nospace_trgm")
    op.execute("DROP INDEX IF EXISTS ix_scp_name_en_trgm")
    op.execute("DROP INDEX IF EXISTS ix_scp_name_nospace_trgm")
