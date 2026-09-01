"""samba_detail_template.gallery_include_sub 기본값 false + 전 템플릿 해제.

운영 방침 변경 — 마켓 썸네일/갤러리(Image1~N)에는 대표이미지 1장만 올리고
추가이미지는 전송하지 않는다. #342 도입 당시 기본값이 true 였기 때문에
(1) 기존 템플릿을 전부 false 로 내리고
(2) 컬럼 server_default 도 false 로 바꿔 신규 템플릿이 다시 켜진 채 생기지 않게 한다.

템플릿 수가 수십 개 수준이라 전건 UPDATE 로 처리한다(hot 테이블 아님).
되돌리려면 화면에서 템플릿별로 다시 체크하면 된다 — downgrade 는 기본값만 복원하고
데이터는 건드리지 않는다(어떤 템플릿이 켜져 있었는지 복원할 수 없으므로).

Revision ID: gallery_include_sub_default_false_01
Revises: kream_refresh_log_01
"""

from alembic import op
from sqlalchemy import text

revision = "gallery_include_sub_default_false_01"
down_revision = "kream_refresh_log_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("SET lock_timeout = '30s'"))
    conn.execute(
        text(
            "ALTER TABLE samba_detail_template "
            "ALTER COLUMN gallery_include_sub SET DEFAULT FALSE"
        )
    )
    conn.execute(
        text(
            "UPDATE samba_detail_template SET gallery_include_sub = FALSE "
            "WHERE gallery_include_sub IS DISTINCT FROM FALSE"
        )
    )
    conn.execute(text("SET lock_timeout = '0'"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            "ALTER TABLE samba_detail_template "
            "ALTER COLUMN gallery_include_sub SET DEFAULT TRUE"
        )
    )
