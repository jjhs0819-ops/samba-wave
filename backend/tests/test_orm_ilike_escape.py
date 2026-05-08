"""SQLAlchemy column.ilike(escape='\\') + escape_like 결과가 LIKE 매칭과 일치하는지 검증.

DB 없이 SQL compile 만으로 ESCAPE 절이 들어가는지, escape_like 결과 패턴이
의도된 형태인지 단위 테스트.
"""

from __future__ import annotations

from sqlalchemy import Column, String, Table, MetaData, select
from sqlalchemy.dialects import postgresql

from backend.core.sql_safe import escape_like


_metadata = MetaData()
_t = Table("t", _metadata, Column("name", String))


def _compile(stmt) -> str:
    # PostgreSQL dialect — ILIKE 가 native 로 컴파일됨.
    return str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


class TestIlikeEscapeCompiles:
    def test_basic_ilike_with_escape(self):
        """`column.ilike(pat, escape='\\\\')` 가 SQL 에 ``ESCAPE`` 절을 포함."""
        stmt = select(_t.c.name).where(_t.c.name.ilike("%foo%", escape="\\"))
        sql = _compile(stmt).upper()
        assert "ILIKE" in sql
        assert "ESCAPE" in sql

    def test_like_with_escape(self):
        stmt = select(_t.c.name).where(_t.c.name.like("%foo%", escape="\\"))
        sql = _compile(stmt).upper()
        assert "LIKE" in sql
        assert "ESCAPE" in sql

    def test_escape_arg_omitted(self):
        """escape 인자 생략 시 ESCAPE 절 없음 (이전 취약 패턴)."""
        stmt = select(_t.c.name).where(_t.c.name.ilike("%foo%"))
        sql = _compile(stmt).upper()
        assert "ESCAPE" not in sql


class TestEscapeLikePatternIntegration:
    """escape_like 결과를 ilike 패턴으로 사용 시 메타 문자가 literal 화 되는지."""

    def test_percent_in_input_becomes_literal(self):
        # raw `%` → escape → `\\%` → 패턴 `%\\%%` 로 사용
        raw = "100%"
        safe = escape_like(raw)
        pattern = f"%{safe}%"
        # 정상 매칭 케이스 — `100% off` 는 literal `100%` 포함
        stmt = select(_t.c.name).where(_t.c.name.ilike(pattern, escape="\\"))
        sql = _compile(stmt)
        # bind 가 literal 로 컴파일되었을 때 패턴이 SQL 안에 반영되는지
        assert "%100" in sql
        # ESCAPE 절 포함
        assert "ESCAPE" in sql.upper()

    def test_underscore_in_input(self):
        raw = "a_b"
        safe = escape_like(raw)
        pattern = f"%{safe}%"
        stmt = select(_t.c.name).where(_t.c.name.ilike(pattern, escape="\\"))
        sql = _compile(stmt)
        assert "ESCAPE" in sql.upper()

    def test_attack_input_neutralized(self):
        # 공격 입력 `%` 단독 — escape 후 `\\%` 가 되어 literal `%` 한 글자만 매칭.
        # 패턴은 `%\\%%` → SQL 의 LIKE 가 `%` 라는 한 글자 substring 검색.
        raw = "%"
        safe = escape_like(raw)
        assert safe == "\\%"
        pattern = f"%{safe}%"
        assert pattern == "%\\%%"

    def test_backslash_input(self):
        raw = "\\"
        safe = escape_like(raw)
        # 한 글자 `\\` → 두 글자 `\\\\`
        assert safe == "\\\\"
        pattern = f"%{safe}%"
        assert pattern == "%\\\\%"
