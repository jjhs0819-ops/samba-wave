"""Brand Risk System Phase 1 — 신규 축 컬럼 + 사건DB/별칭 테이블 (additive only)

Revision ID: add_brand_risk_axes_0811
Revises: add_brand_restriction_0723
Create Date: 2026-08-11

2026-08 데이터 감사(로컬 DB 실측)에서 확인된 사실을 반영한다:
  - samba_brand_restriction 기존 3건(하바이아나스/퍼글러/브룩스)은 전부
    coupang_api 자동판별뿐이고 verdict 단일축이라, "브룩스: 지재권 위험은
    낮지만 쿠팡 사전소명은 필요"처럼 서로 다른 두 축을 동시에 표현하지 못한다.
  - 이 마이그레이션은 그 표현력만 추가한다. 기존 컬럼(brand/brand_key/
    verdict/soomyeong/ipr/markets/note/source/coupang_uid_required/
    coupang_matched/coupang_checked_at)은 하나도 건드리지 않는다. 새 컬럼은
    전부 nullable — 기존 3건 값과 BrandGuardService.check() 판정은 마이그레이션
    전후 완전히 동일하다.
  - samba_forbidden_word(3,632건)는 이 마이그레이션에서 전혀 다루지 않는다.
    브랜드 리스크 DB가 아니라 별개 목적의 기존 상품명 필터 시스템으로 간주한다
    (brand/legacy_conflict.py 참고 — 조회만 하고 수정하지 않음).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "add_brand_risk_axes_0811"
down_revision = "add_brand_restriction_0723"
branch_labels = None
depends_on = None

RESTRICTION_TABLE = "samba_brand_restriction"
CASE_TABLE = "samba_brand_risk_case"
ALIAS_TABLE = "samba_brand_alias"

_NEW_RESTRICTION_COLUMNS = (
    ("ip_risk_level", sa.Text()),
    ("coupang_pre_auth", sa.Text()),
    ("marq_vision", sa.Boolean()),
    ("marketplace_risk", postgresql.JSON(astext_type=sa.Text())),
    ("image_risk_note", sa.Text()),
    ("confidence", sa.Text()),
)


def _has_table(table: str) -> bool:
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
        {"t": table},
    ).fetchone()
    return row is not None


def _has_column(table: str, column: str) -> bool:
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return row is not None


def _has_index(index_name: str) -> bool:
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :i"),
        {"i": index_name},
    ).fetchone()
    return row is not None


def upgrade() -> None:
    # ── 1) samba_brand_restriction — nullable 신규 축 컬럼만 추가 ──
    for name, col_type in _NEW_RESTRICTION_COLUMNS:
        if not _has_column(RESTRICTION_TABLE, name):
            op.add_column(RESTRICTION_TABLE, sa.Column(name, col_type, nullable=True))

    if not _has_index("ix_brand_restriction_ip_risk_level"):
        op.create_index(
            "ix_brand_restriction_ip_risk_level",
            RESTRICTION_TABLE,
            ["ip_risk_level"],
        )

    # ── 2) samba_brand_risk_case — 사건DB. append-only, FK 없음(의도적) ──
    # MASTER.md 브랜드 대부분이 아직 samba_brand_restriction 에 없으므로(감사
    # 확인) FK 를 걸면 사건 적재 자체가 막힌다. normalized_brand 텍스트 매칭만.
    if not _has_table(CASE_TABLE):
        op.create_table(
            CASE_TABLE,
            sa.Column("case_id", sa.String(length=30), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=True),
            sa.Column("brand", sa.Text(), nullable=False),
            sa.Column("normalized_brand", sa.Text(), nullable=False),
            sa.Column("marketplace", sa.Text(), nullable=True),
            sa.Column("report_type", sa.Text(), nullable=True),
            sa.Column("rights_holder_or_agent", sa.Text(), nullable=True),
            sa.Column("contact_channel", sa.Text(), nullable=True),
            sa.Column("reporter", sa.Text(), nullable=True),
            sa.Column("experience_type", sa.Text(), nullable=True),
            sa.Column("image_state", sa.Text(), nullable=True),
            sa.Column("result", sa.Text(), nullable=True),
            sa.Column("account_impact", sa.Text(), nullable=True),
            sa.Column("confidence", sa.Text(), nullable=True),
            sa.Column("source", sa.Text(), nullable=True),
            sa.Column("raw_summary", sa.Text(), nullable=True),
            sa.Column("incident_date", sa.Date(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_brand_risk_case_normalized_brand", CASE_TABLE, ["normalized_brand"]
        )
        op.create_index("ix_brand_risk_case_tenant", CASE_TABLE, ["tenant_id"])
        op.create_index(
            "ix_brand_risk_case_incident_date", CASE_TABLE, ["incident_date"]
        )

    # ── 3) samba_brand_alias — 표기변형(ARC`TERYX 등) → canonical 매핑 ──
    if not _has_table(ALIAS_TABLE):
        op.create_table(
            ALIAS_TABLE,
            sa.Column("id", sa.String(length=30), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=True),
            sa.Column("canonical_key", sa.Text(), nullable=False),
            sa.Column("alias_raw", sa.Text(), nullable=False),
            sa.Column("alias_key", sa.Text(), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_brand_alias_canonical", ALIAS_TABLE, ["canonical_key"])
        op.create_index("ix_brand_alias_tenant", ALIAS_TABLE, ["tenant_id"])
        # 브랜드 별칭은 전역(tenant_id=NULL)이 기본 — samba_brand_restriction 의
        # ux_brand_restriction_key 와 동일 이유로 NULLS NOT DISTINCT 필요.
        op.execute(
            "CREATE UNIQUE INDEX ux_brand_alias_key "
            f"ON {ALIAS_TABLE} (tenant_id, alias_key) NULLS NOT DISTINCT"
        )


def downgrade() -> None:
    if _has_table(ALIAS_TABLE):
        op.execute("DROP INDEX IF EXISTS ux_brand_alias_key")
        if _has_index("ix_brand_alias_tenant"):
            op.drop_index("ix_brand_alias_tenant", table_name=ALIAS_TABLE)
        if _has_index("ix_brand_alias_canonical"):
            op.drop_index("ix_brand_alias_canonical", table_name=ALIAS_TABLE)
        op.drop_table(ALIAS_TABLE)

    if _has_table(CASE_TABLE):
        if _has_index("ix_brand_risk_case_incident_date"):
            op.drop_index("ix_brand_risk_case_incident_date", table_name=CASE_TABLE)
        if _has_index("ix_brand_risk_case_tenant"):
            op.drop_index("ix_brand_risk_case_tenant", table_name=CASE_TABLE)
        if _has_index("ix_brand_risk_case_normalized_brand"):
            op.drop_index("ix_brand_risk_case_normalized_brand", table_name=CASE_TABLE)
        op.drop_table(CASE_TABLE)

    if _has_index("ix_brand_restriction_ip_risk_level"):
        op.drop_index(
            "ix_brand_restriction_ip_risk_level", table_name=RESTRICTION_TABLE
        )
    for name, _ in reversed(_NEW_RESTRICTION_COLUMNS):
        if _has_column(RESTRICTION_TABLE, name):
            op.drop_column(RESTRICTION_TABLE, name)
