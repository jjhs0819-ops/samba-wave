"""samba_collected_product 적립금 사용 제한 컬럼 추가 (is_point_restricted)

Revision ID: 202604281530_add_pt_restrict
Revises: 202604251130_add_customer_note
Create Date: 2026-04-28 15:30:00.000000

배경:
  무신사 상품 상세 API에 isRestictedUsePoint(적립금 사용 제한) 플래그가 있어
  적립금 사용 가능 상품과 불가 상품을 구분할 수 있다.
  정책의 "소싱처별 추가 마진"에서 적립금 사용 가능 상품에만 추가 마진을
  적용하는 옵션을 지원하기 위해 상품 단위로 해당 플래그를 저장한다.

  - True  : 적립금 사용 불가 상품
  - False : 적립금 사용 가능 상품
  - NULL  : 미수집 또는 지원하지 않는 소싱처

idempotent 처리:
  entrypoint.sh가 부팅 시 'alembic stamp <baseline>' 후 'alembic upgrade heads'를
  매번 실행하므로 두 번째 컨테이너(blue/green) 부팅 시 이미 적용된 컬럼을 다시
  추가하려다 DuplicateColumnError 발생. 이를 방지하기 위해 raw SQL의 IF NOT EXISTS
  패턴을 사용한다 (이전 마이그레이션 add_customer_note와 동일 방식).
"""

from typing import Sequence, Union

from alembic import op


revision: str = "202604281530_add_pt_restrict"
down_revision: Union[str, None] = "202604251130_add_customer_note"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # DO 블록으로 사전 확인: 컬럼이 이미 존재하면 ALTER TABLE 자체를 건너뜀
    # (ALTER TABLE은 IF NOT EXISTS여도 AccessExclusiveLock 필요 → 바쁜 테이블에서 lock timeout 유발)
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'samba_collected_product'
                  AND column_name = 'is_point_restricted'
            ) THEN
                ALTER TABLE samba_collected_product ADD COLUMN is_point_restricted BOOLEAN;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE samba_collected_product DROP COLUMN IF EXISTS is_point_restricted"
    )
