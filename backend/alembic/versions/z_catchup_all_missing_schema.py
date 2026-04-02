"""전체 스키마 동기화 — 누락된 테이블·컬럼 일괄 추가

Revision ID: z_catchup_001
Revises: 26dd9b23892a, bcb782b5afaa, f71132fc5b81
Create Date: 2026-04-02

3개 HEAD 머지 + Cloud SQL에 누락된 모든 컬럼/테이블 보완.
IF NOT EXISTS를 사용하므로 이미 존재하는 항목은 건너뜀.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers
revision: str = "z_catchup_001"
down_revision: Union[str, Sequence[str]] = (
    "26dd9b23892a",
    "bcb782b5afaa",
    "f71132fc5b81",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ──────────────────────────────────────────────
    # 1. samba_return 누락 컬럼 (23개)
    # ──────────────────────────────────────────────
    _sr = [
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS order_number TEXT",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS product_image TEXT",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS product_name TEXT",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS customer_name TEXT",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS business_name TEXT",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS market TEXT",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS customer_phone TEXT",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS confirmed BOOLEAN DEFAULT FALSE",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS order_date TIMESTAMPTZ",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS check_date TIMESTAMPTZ",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS settlement_amount FLOAT",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS recovery_amount FLOAT",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS memo TEXT",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS product_location TEXT",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS customer_address TEXT",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS return_link TEXT",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS return_source TEXT",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS region TEXT",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS return_request_date TIMESTAMPTZ",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS market_order_status TEXT",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS completion_detail TEXT DEFAULT '진행중'",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS customer_order_no TEXT DEFAULT 'return_incomplete'",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS original_order_no TEXT DEFAULT 'return_incomplete'",
        "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS tenant_id TEXT",
    ]
    for sql in _sr:
        op.execute(sql)

    # ──────────────────────────────────────────────
    # 2. samba_tenants 테이블 생성
    # ──────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS samba_tenants (
            id VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            owner_user_id VARCHAR NOT NULL DEFAULT '',
            plan VARCHAR NOT NULL DEFAULT 'free',
            limits JSON,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """)

    # ──────────────────────────────────────────────
    # 3. samba_sourcing_account 테이블 생성
    # ──────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS samba_sourcing_account (
            id VARCHAR(30) PRIMARY KEY,
            tenant_id VARCHAR,
            site_name TEXT NOT NULL,
            account_label TEXT NOT NULL,
            username TEXT NOT NULL,
            password TEXT NOT NULL,
            chrome_profile TEXT,
            memo TEXT,
            balance FLOAT,
            balance_updated_at TIMESTAMPTZ,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            additional_fields JSON,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_samba_sourcing_account_site_name "
        "ON samba_sourcing_account (site_name)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_samba_sourcing_account_is_active "
        "ON samba_sourcing_account (is_active)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_samba_sourcing_account_tenant_id "
        "ON samba_sourcing_account (tenant_id)"
    )

    # ──────────────────────────────────────────────
    # 4. SNS 포스팅 테이블 4개
    # ──────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS samba_wp_site (
            id VARCHAR(30) PRIMARY KEY,
            tenant_id VARCHAR,
            site_url TEXT NOT NULL,
            username VARCHAR(100) NOT NULL,
            app_password TEXT NOT NULL,
            site_name VARCHAR(200),
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_samba_wp_site_tenant_id "
        "ON samba_wp_site (tenant_id)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS samba_sns_keyword_group (
            id VARCHAR(30) PRIMARY KEY,
            tenant_id VARCHAR,
            name VARCHAR(100) NOT NULL,
            category VARCHAR(50) NOT NULL,
            keywords JSON NOT NULL DEFAULT '[]',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_samba_sns_keyword_group_tenant_id "
        "ON samba_sns_keyword_group (tenant_id)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS samba_sns_post (
            id VARCHAR(30) PRIMARY KEY,
            tenant_id VARCHAR,
            wp_site_id VARCHAR(30),
            wp_post_id INTEGER,
            title TEXT NOT NULL,
            content TEXT,
            category VARCHAR(100),
            keyword VARCHAR(200),
            source_url TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            language VARCHAR(5) NOT NULL DEFAULT 'ko',
            product_ids JSON,
            published_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_samba_sns_post_tenant_id "
        "ON samba_sns_post (tenant_id)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS samba_sns_auto_config (
            id VARCHAR(30) PRIMARY KEY,
            tenant_id VARCHAR,
            wp_site_id VARCHAR(30) NOT NULL,
            interval_minutes INTEGER NOT NULL DEFAULT 20,
            max_daily_posts INTEGER NOT NULL DEFAULT 150,
            is_running BOOLEAN NOT NULL DEFAULT FALSE,
            language VARCHAR(5) NOT NULL DEFAULT 'ko',
            include_product_banner BOOLEAN NOT NULL DEFAULT TRUE,
            product_banner_html TEXT,
            today_count INTEGER NOT NULL DEFAULT 0,
            last_posted_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_samba_sns_auto_config_tenant_id "
        "ON samba_sns_auto_config (tenant_id)"
    )


def downgrade() -> None:
    # 다운그레이드는 지원하지 않음 (안전을 위해)
    pass
