"""크림 라이브 입찰 스냅샷 테이블 추가.

kream_live_asks 는 크림 통합 사이클이 매 사이클 TRUNCATE+INSERT 로 되쓰는
"현재 살아있는 입찰" 스냅샷이다(_write_live_asks_snapshot). 운영 DB 에는 손으로
만들어 둔 채 마이그레이션이 없어서, 새 환경(로컬 등)에서는 테이블이 생기지 않는다.

없을 때 증상:
  - 대시보드 '소싱처별 수집현황'이 통째로 빈다. 집계 쿼리(_run_brand_site) 안에
    크림 등록판정용 `IN (SELECT product_id FROM kream_live_asks)` 가 들어있는데,
    Postgres 는 문장 전체를 파싱단계에서 거부하므로 크림과 무관한 무신사/ABCmart
    집계까지 같이 죽는다. 부분 실패 처리라 예외는 warning 으로만 남는다.
  - 크림 리셀 입찰 집계(_run_resell), 워룸 섀도 집계도 동일하게 실패한다.
  - 스냅샷 쓰기는 "스냅샷 실패(무시)" 만 남기고 넘어간다.

빈 테이블이어도 크림 행이 등록 0 으로 잡힐 뿐 나머지 소싱처는 정상 집계된다.

Revision ID: kream_live_asks_01
Revises: gallery_include_sub_default_false_01
"""

from alembic import op
import sqlalchemy as sa

revision = "kream_live_asks_01"
down_revision = "gallery_include_sub_default_false_01"
branch_labels = None
depends_on = None

_TABLE = "kream_live_asks"


def upgrade() -> None:
    # 이미 만들어 쓰던 환경(운영)이 있어 존재하면 건너뛴다 — 운영 데이터 보존.
    bind = op.get_bind()
    if sa.inspect(bind).has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        # product_id 는 resell_matches->'kream'->>'product_id' (jsonb text) 와
        # 직접 비교되므로 반드시 text — 숫자형이면 IN 비교에서 타입 에러난다.
        sa.Column("product_id", sa.Text(), nullable=False),
        # 사이즈(옵션)명. 상품당 여러 입찰이 있어 product_id 는 유일하지 않다.
        sa.Column("option", sa.Text(), nullable=False, server_default=""),
        sa.Column("price", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # 등록판정 서브쿼리(IN)와 워룸 조인이 product_id 로 탄다.
    # UNIQUE 는 걸지 않는다 — 스냅샷 쓰기가 TRUNCATE+INSERT 라 제약 없이도
    # 중복이 누적되지 않고, 운영 테이블의 기존 형태와도 어긋나지 않는다.
    op.create_index(f"ix_{_TABLE}_product_id", _TABLE, ["product_id"])


def downgrade() -> None:
    op.drop_index(f"ix_{_TABLE}_product_id", table_name=_TABLE)
    op.drop_table(_TABLE)
