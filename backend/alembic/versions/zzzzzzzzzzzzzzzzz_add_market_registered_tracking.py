"""samba_collected_product에 first_market_registered_at + fully_unregistered_at 추가

배경:
- 대시보드 신규등록/마켓삭제 카운트를 "상품 단위" 0↔≥1 전환 기준으로 정확히 집계하기 위함
- 이벤트 로그(samba_monitor_event)는 마켓 액션별로 emit되어 같은 상품 다중 마켓 시 중복 카운트됨
- registered_accounts(JSONB)의 0↔≥1 전환 시점을 상품 row에 직접 저장

idempotent:
- IF NOT EXISTS raw SQL 사용 (op.add_column 금지 — CLAUDE.md 규칙)

backfill:
- 현재 registered_accounts가 비어있지 않은 상품 → 가장 빠른 market_registered 이벤트 시각으로 first_market_registered_at 설정 (이벤트 없으면 created_at)
- 현재 registered_accounts가 비어있는 상품 → 가장 늦은 market_deleted 이벤트 시각으로 fully_unregistered_at 설정 (이벤트 없으면 NULL 유지)

Revision ID: zzzzzzzzzzzzzzzzz_add_market_registered_tracking
Revises: zzzzzzzzzzzzzzzz_add_addon_options
Create Date: 2026-05-12 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "zzzzzzzzzzzzzzzzz_add_market_registered_tracking"
down_revision: Union[str, Sequence[str], None] = "zzzzzzzzzzzzzzzz_add_addon_options"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 컬럼 추가 (idempotent)
    op.execute(
        """
        ALTER TABLE samba_collected_product
        ADD COLUMN IF NOT EXISTS first_market_registered_at TIMESTAMPTZ
        """
    )
    op.execute(
        """
        ALTER TABLE samba_collected_product
        ADD COLUMN IF NOT EXISTS fully_unregistered_at TIMESTAMPTZ
        """
    )

    # 인덱스 추가 (대시보드 일별 집계 쿼리 가속)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_scp_first_market_registered_at
        ON samba_collected_product (first_market_registered_at)
        WHERE first_market_registered_at IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_scp_fully_unregistered_at
        ON samba_collected_product (fully_unregistered_at)
        WHERE fully_unregistered_at IS NOT NULL
        """
    )

    # backfill: 마켓등록된 상품의 first_market_registered_at
    # 1) 이벤트가 있는 상품 — 가장 빠른 market_registered 시각
    op.execute(
        """
        UPDATE samba_collected_product cp
        SET first_market_registered_at = ev.first_at
        FROM (
            SELECT product_id, MIN(created_at) AS first_at
            FROM samba_monitor_event
            WHERE event_type = 'market_registered'
              AND product_id IS NOT NULL
            GROUP BY product_id
        ) ev
        WHERE cp.id = ev.product_id
          AND cp.first_market_registered_at IS NULL
          AND cp.registered_accounts IS NOT NULL
          AND jsonb_typeof(cp.registered_accounts) = 'array'
          AND jsonb_array_length(cp.registered_accounts) > 0
        """
    )
    # 2) 이벤트 없는 상품(이미 등록된 채로 보존기간 초과) — created_at으로 fallback
    op.execute(
        """
        UPDATE samba_collected_product
        SET first_market_registered_at = created_at
        WHERE first_market_registered_at IS NULL
          AND registered_accounts IS NOT NULL
          AND jsonb_typeof(registered_accounts) = 'array'
          AND jsonb_array_length(registered_accounts) > 0
        """
    )

    # backfill: 전부 삭제된 상품의 fully_unregistered_at
    op.execute(
        """
        UPDATE samba_collected_product cp
        SET fully_unregistered_at = ev.last_at
        FROM (
            SELECT product_id, MAX(created_at) AS last_at
            FROM samba_monitor_event
            WHERE event_type = 'market_deleted'
              AND product_id IS NOT NULL
            GROUP BY product_id
        ) ev
        WHERE cp.id = ev.product_id
          AND cp.fully_unregistered_at IS NULL
          AND (
              cp.registered_accounts IS NULL
              OR jsonb_typeof(cp.registered_accounts) != 'array'
              OR jsonb_array_length(cp.registered_accounts) = 0
          )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_scp_fully_unregistered_at")
    op.execute("DROP INDEX IF EXISTS ix_scp_first_market_registered_at")
    op.execute(
        "ALTER TABLE samba_collected_product DROP COLUMN IF EXISTS fully_unregistered_at"
    )
    op.execute(
        "ALTER TABLE samba_collected_product DROP COLUMN IF EXISTS first_market_registered_at"
    )
