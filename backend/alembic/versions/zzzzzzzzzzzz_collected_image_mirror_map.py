"""samba_collected_product 에 image_mirror_map JSONB 추가 (#249)

배경:
- 차단 도메인 이미지 R2 미러링 결과(원본URL → R2URL) 영속화.
- 프로세스 캐시(ImageTransformService._R2_MIRROR_CACHE) 만으로는 배포/재시작
  직후 다시 다운로드 발생 → DB 매핑 추가로 동일 상품 N마켓×재전송 비용 0 보장.

idempotent:
- samba_collected_product 는 hot 테이블 → information_schema 사전체크
- 누락 컬럼만 raw SQL ADD COLUMN (op.add_column 금지)
- ALTER 직전 idle in transaction 정리 + lock_timeout 5분

Revision ID: zzzzzzzzzzzz_collected_image_mirror_map
Revises: zzzzzzzzzzz_coupang_cancel_columns
Create Date: 2026-05-27 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "zzzzzzzzzzzz_collected_image_mirror_map"
down_revision: Union[str, Sequence[str], None] = "zzzzzzzzzzz_coupang_cancel_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = {
        row[0]
        for row in conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'samba_collected_product' "
                "AND column_name = 'image_mirror_map'"
            )
        ).fetchall()
    }
    if "image_mirror_map" in existing:
        return

    op.execute(
        """
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE state = 'idle in transaction'
          AND pid <> pg_backend_pid()
        """
    )
    op.execute("SET LOCAL lock_timeout = '5min'")
    op.execute("ALTER TABLE samba_collected_product ADD COLUMN image_mirror_map JSONB")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE samba_collected_product DROP COLUMN IF EXISTS image_mirror_map"
    )
