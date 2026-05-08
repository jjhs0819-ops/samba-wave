"""SQL injection 방어 유틸 — LIKE 패턴 와일드카드 이스케이프 등."""

from __future__ import annotations

# PostgreSQL LIKE 의 와일드카드 메타 문자.
# `%`: 0개 이상의 문자, `_`: 정확히 1개 문자.
# 사용자 입력에 포함된 와일드카드를 리터럴로 강제하려면 이스케이프 필요.
# `\` 가 첫번째인 이유: 다른 메타 치환의 결과를 다시 이스케이프하지 않으려면
# 가장 먼저 처리해야 한다 (예: `%` 가 `\%` 로 바뀐 후 `\` 를 다시 이스케이프하면
# `\\%` 가 되어 의미 변형).
_LIKE_META_CHARS: tuple[str, ...] = ("%", "_")


def escape_like(value: str, escape_char: str = "\\") -> str:
    """LIKE 패턴에 사용할 사용자 입력의 와일드카드를 이스케이프한다.

    Args:
        value: 사용자 입력 문자열.
        escape_char: 이스케이프 문자 (default: ``\\``). 호출부 SQL 의 ``ESCAPE '\\'``
            절과 일치해야 한다.

    Returns:
        ``\\``, ``%``, ``_`` 가 ``escape_char`` 로 이스케이프된 안전한 문자열.

    예::

        pattern = f"%{escape_like(user_input)}%"
        sql = "... WHERE col LIKE :pattern ESCAPE '\\\\'"

    Note:
        반드시 호출부 SQL 에 ``ESCAPE '<escape_char>'`` 절을 함께 명시해야
        한다. PostgreSQL 의 LIKE 기본 escape 는 ``\\`` 이지만 명시하지 않으면
        ``standard_conforming_strings`` 설정 등에 따라 동작이 달라질 수 있다.
    """
    if not isinstance(value, str):
        value = str(value)

    # `\\` 를 가장 먼저 치환해야 다른 메타 치환의 결과를 다시 이스케이프하지 않는다.
    result = value.replace(escape_char, escape_char + escape_char)
    for meta in _LIKE_META_CHARS:
        if meta == escape_char:
            continue
        result = result.replace(meta, escape_char + meta)
    return result


__all__ = ["escape_like"]
