"""samba_tetris_assignment 에 excluded 컬럼 추가 — 전송잡 등록에서 배제 플래그.

테트리스 보드에서 브랜드 블럭을 클릭해 토글하는 '배제' 상태를 영속화한다.
excluded=True 인 배치는 sync_all 의 transmit 잡 생성에서 제외된다.

Revision ID: zzzzzzzzz_add_tetris_excluded
Revises: zzzzzzzz_add_samba_sourcing_job
Create Date: 2026-05-09
"""

from alembic import op


revision = "zzzzzzzzz_add_tetris_excluded"
down_revision = "zzzzzzzz_add_samba_sourcing_job"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 기존 레코드는 excluded=False 로 backfill (idempotent)
    op.execute(
        """
        ALTER TABLE samba_tetris_assignment
        ADD COLUMN IF NOT EXISTS excluded BOOLEAN NOT NULL DEFAULT FALSE
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE samba_tetris_assignment DROP COLUMN IF EXISTS excluded")
