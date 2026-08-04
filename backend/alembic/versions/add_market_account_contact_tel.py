"""마켓 계정에 사업자 연락처(contact_tel) 추가.

상품 고시정보의 "A/S 책임자 또는 소비자상담 관련 전화번호"(법정 필수)를 계정 설정에서
입력받아 쓰기 위한 컬럼. 크림 고시등록이 이 값을 사용한다.

Revision ID: mkt_acct_contact_tel
Revises: remove_sns_posting_0802
"""

from alembic import op

revision = "mkt_acct_contact_tel"
down_revision = "remove_sns_posting_0802"
branch_labels = None
depends_on = None


def _has_column() -> bool:
    return bool(
        op.get_bind()
        .exec_driver_sql(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='samba_market_account' AND column_name='contact_tel'"
        )
        .first()
    )


def upgrade() -> None:
    # 이미 있으면 ALTER 자체를 건너뛴다 — ADD COLUMN IF NOT EXISTS 도 AccessExclusiveLock 을
    # 잠깐 잡아 활성 트랜잭션과 부딪힌다.
    if not _has_column():
        op.execute("ALTER TABLE samba_market_account ADD COLUMN contact_tel TEXT")


def downgrade() -> None:
    if _has_column():
        op.execute("ALTER TABLE samba_market_account DROP COLUMN contact_tel")
