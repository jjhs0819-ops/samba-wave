"""samba_extension_key 테이블 추가 — 확장앱 테넌트별 API 키 영속화.

글로벌 단일 키 대신 사용자별 키를 발급해 테넌트 간 격리 및 revoke 가능하도록 한다.
평문 키는 발급 시 1회만 응답에 포함되며 DB에는 SHA-256 hash만 저장.

Revision ID: zzzzzzzzzz_add_samba_extension_key
Revises: zzzzzzzzz_add_tetris_excluded
Create Date: 2026-05-09
"""

from alembic import op


revision = "zzzzzzzzzz_add_samba_extension_key"
down_revision = "zzzzzzzzz_add_tetris_excluded"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS samba_extension_key (
            id              VARCHAR(40) PRIMARY KEY,
            key_hash        VARCHAR(128) NOT NULL,
            tenant_id       VARCHAR(40),
            user_id         VARCHAR(40) NOT NULL,
            label           VARCHAR(80),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_used_at    TIMESTAMPTZ,
            expires_at      TIMESTAMPTZ,
            revoked_at      TIMESTAMPTZ,
            note            TEXT
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_samba_extension_key_key_hash
        ON samba_extension_key (key_hash)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_samba_extension_key_tenant_id
        ON samba_extension_key (tenant_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_samba_extension_key_user_id
        ON samba_extension_key (user_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_samba_extension_key_active
        ON samba_extension_key (tenant_id, revoked_at)
        WHERE revoked_at IS NULL
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS samba_extension_key")
