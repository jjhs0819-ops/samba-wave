"""송장번호 정규화(normalize_tracking_number) 단위 테스트.

마켓 전송·저장·조회를 한 규칙으로 통일: 구분자(슬래시·하이픈·공백 등) 제거,
영숫자만 유지. 국내(숫자)뿐 아니라 크림/해외송장(영문+숫자) 보존이 핵심.
"""

import pytest

from backend.domain.samba.order.dispatch_service import normalize_tracking_number


@pytest.mark.parametrize(
    "raw, expected",
    [
        # 하이픈/슬래시/공백 제거
        ("6993-6903-5384", "699369035384"),
        ("3184/1234/5678", "318412345678"),
        ("  318412345678  ", "318412345678"),
        ("3184 1234 5678", "318412345678"),
        ("3184.1234.5678", "318412345678"),
        # 이미 깨끗한 국내 숫자 — 그대로
        ("318412345678", "318412345678"),
        # 해외/크림 송장(영문+숫자) — 영문 보존, 구분자만 제거
        ("EE123456789KR", "EE123456789KR"),
        ("EE-1234-5678-9KR", "EE123456789KR"),
        # 빈값/None 방어
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_tracking_number(raw, expected):
    assert normalize_tracking_number(raw) == expected
