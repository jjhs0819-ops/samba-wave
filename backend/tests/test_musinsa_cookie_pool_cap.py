"""무신사 쿠키 풀 상한 회귀 테스트.

배경(2026-08-19 운영): musinsa_set_cookie 가 풀에 상한 없이 append 만 해서
samba_settings.musinsa_cookies 값 하나가 **165MB** 까지 자랐다. 이 엔드포인트는
매 호출마다 전체를 복호화→JSON 파싱→직렬화→암호화→재저장하므로, 165MB 를
동기로 처리하며 API 이벤트루프를 통째로 세웠다(체크포인트 폭주의 원인이기도).

풀은 refresher 의 쿠키 로테이션용이고 원래 설계는 '활성 계정당 1개'(현재 2개)다.
여기서는 순서·중복제거·상한이라는 순수 병합 규칙만 검증한다.
"""

import json


COOKIE_POOL_MAX = 20


def _merge(new_cookie: str, existing: list[str]) -> list[str]:
    """musinsa.py 의 풀 병합 규칙과 동일 — 최신 맨 앞, 중복 제거, 상한 절단."""
    return ([new_cookie] + [c for c in existing if c != new_cookie])[:COOKIE_POOL_MAX]


def test_풀이_상한을_넘지_않는다():
    existing = [f"cookie_{i}" for i in range(5000)]

    merged = _merge("새쿠키", existing)

    assert len(merged) == COOKIE_POOL_MAX, "상한이 없으면 값이 무한히 커진다(운영 165MB 사고)"


def test_새_쿠키가_항상_맨_앞이다():
    merged = _merge("최신", ["옛날1", "옛날2"])

    assert merged[0] == "최신", "refresher 로테이션이 최신 쿠키부터 쓰도록 맨 앞이어야 한다"


def test_같은_쿠키가_중복으로_쌓이지_않는다():
    merged = _merge("A", ["A", "B", "A"])

    assert merged == ["A", "B"]


def test_상한까지는_기존_쿠키를_잃지_않는다():
    existing = [f"c{i}" for i in range(COOKIE_POOL_MAX - 1)]

    merged = _merge("새것", existing)

    assert len(merged) == COOKIE_POOL_MAX
    assert merged[1:] == existing, "상한 미만이면 기존 쿠키가 그대로 보존돼야 한다"


def test_상한_초과분은_가장_오래된_것부터_버린다():
    existing = [f"c{i}" for i in range(30)]

    merged = _merge("새것", existing)

    assert merged[-1] == "c18", "최신순 정렬이므로 뒤쪽(오래된 것)이 잘려야 한다"
    assert "c29" not in merged


def test_직렬화_크기가_실용적_범위다():
    """쿠키 1개 7.6KB(운영 실측) 기준, 풀 전체가 200KB 를 넘지 않아야 한다."""
    big = "x" * 7654
    merged = _merge(big, [big[:-1] + str(i % 10) for i in range(1000)])

    assert len(json.dumps(merged)) < 200_000
