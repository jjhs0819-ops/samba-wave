"""sourcing_recipes 테이블 추가

Revision ID: z_add_sourcing_recipes
Revises: z_elevenst_ord_prd_seq
Create Date: 2026-05-03 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "z_add_sourcing_recipes"
down_revision: Union[str, None] = "z_elevenst_ord_prd_seq"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS sourcing_recipes (
            id SERIAL PRIMARY KEY,
            site_name VARCHAR(50) NOT NULL UNIQUE,
            version VARCHAR(20) NOT NULL,
            steps JSON NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT true,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sourcing_recipes_site_name
        ON sourcing_recipes (site_name)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sourcing_recipes")
