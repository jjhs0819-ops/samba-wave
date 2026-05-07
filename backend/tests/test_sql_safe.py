"""LIKE 와일드카드 이스케이프 (escape_like) 단위 테스트."""

from __future__ import annotations

import pytest

from backend.core.sql_safe import escape_like


class TestEscapeLike:
    def test_passthrough_when_no_meta(self):
        assert escape_like("hello") == "hello"
        assert escape_like("12345") == "12345"

    def test_escapes_percent(self):
        # `%` → `\%`
        assert escape_like("50%") == "50\\%"

    def test_escapes_underscore(self):
        # `_` → `\_`
        assert escape_like("a_b") == "a\\_b"

    def test_escapes_backslash_first(self):
        # 백슬래시 자체가 escape_char 이므로 가장 먼저 이중화되어야 한다.
        # `\` → `\\`
        assert escape_like("a\\b") == "a\\\\b"

    def test_escapes_combined(self):
        # 모든 메타 문자 동시 포함
        assert escape_like("a_b%c\\d") == "a\\_b\\%c\\\\d"

    def test_attack_pattern_neutralized(self):
        # 공격 입력: `%` 만 넣어 LIKE '%%%' 로 풀려 모든 row 매칭하려는 시도.
        attacker = "%"
        safe = escape_like(attacker)
        # 결과 패턴 `%\%%` 는 백분율 기호 한 글자 부분문자열만 매칭.
        assert safe == "\\%"

    def test_empty_string(self):
        assert escape_like("") == ""

    def test_non_string_coerced(self):
        # 호출부에서 ``str(...)`` 를 잊어도 안전하도록 강제 변환.
        assert escape_like(12345) == "12345"  # type: ignore[arg-type]

    def test_custom_escape_char(self):
        # `!` 를 escape_char 로 사용 (PostgreSQL ESCAPE '!')
        assert escape_like("50%", escape_char="!") == "50!%"
        assert escape_like("a_b", escape_char="!") == "a!_b"
        # 입력의 `!` 는 이중화되어야 함
        assert escape_like("a!b", escape_char="!") == "a!!b"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("100% off", "100\\% off"),
        ("under_score", "under\\_score"),
        ("normal", "normal"),
        ("", ""),
        ("\\\\", "\\\\\\\\"),
    ],
)
def test_parametrized(raw: str, expected: str):
    assert escape_like(raw) == expected
