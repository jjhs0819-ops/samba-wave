"""금지어 단어 경계 — 실제 오탐 상품명으로 검증.

2026-08-15 전송 로그에서 나온 실제 스킵 사례를 그대로 넣었다.
"""

import pytest

from backend.domain.samba.forbidden.matcher import (
    find_forbidden_hit,
    matches_forbidden,
)


@pytest.mark.parametrize(
    ("word", "name"),
    [
        ("sex", "푸마 x 세이스카이 숏 슬리브 티셔츠 UNISEX PUMA X SAYSKY SS TEE"),
        ("TSI", "W) THINK OUTSIDE 퀵드라이 반팔티셔츠 BLACK CHARCOAL"),
        ("AMI", "GOCap SC - Comp - WWM 26 - Miami 마이애미"),
        ("JMW", "위크론 지오 쇼트 슬리브 집 셔츠 여 CHARCOAL GRAY JBWJMWZH041"),
        ("gnc", "푸마 X GGNC 와일드플라워 티 - 퍼지 / 635617-01"),
        ("gnc", "푸마 X GGNC 5 패널 캡 - 다크 세이지 / 027047-01"),
    ],
)
def test_영문금지어_부분일치_오탐이_풀린다(word, name):
    assert matches_forbidden(name, word) is False


@pytest.mark.parametrize(
    ("word", "name"),
    [
        ("vans", "[VANS X SOON EASY] 프리미엄 어센틱 44 LX - 타우페 미스트"),
        ("vans", "어센틱 - (I Love My Vans) 화이트 / VN000Z75W001"),
        ("MLB", "MLB 뉴욕양키스 볼캡"),
        ("DIOR", "DIOR 새들백"),
        ("sex", "정품sex상품"),  # 한글에 둘러싸인 영문 — \b 였다면 놓쳤다
        ("gnc", "GNC 비타민"),
        ("gnc", "gnc 비타민"),  # 대소문자 무시
        ("TSI", "브랜드 (TSI) 티셔츠"),  # 괄호는 경계
    ],
)
def test_진짜_금지어는_계속_막힌다(word, name):
    assert matches_forbidden(name, word) is True


@pytest.mark.parametrize(
    ("word", "name"),
    [
        ("포켓몬", "푸마 x 포켓몬스터 티셔츠"),  # 합성어 — 한글은 부분일치 유지
        ("나이키", "나이키를 신다"),  # 조사가 붙어도 잡혀야 한다
        ("루미나", "VIVID 루미나 듀얼코어 3피스 골프공 12구"),
    ],
)
def test_한글금지어는_부분일치_유지(word, name):
    assert matches_forbidden(name, word) is True


def test_한글_부분일치_유지의_대가():
    """'루미나' 가 아디다스 색상명 '알루미나' 를 잡는 오탐은 남는다.

    한글에 단어 경계를 적용하면 위 test_한글금지어는_부분일치_유지 가 전부 깨진다.
    이건 매칭 방식이 아니라 금지어 목록에서 다룰 문제 — 의도적으로 남긴 동작이라
    바뀌면 알아채도록 테스트로 고정해 둔다.
    """
    assert (
        matches_forbidden("루스 컷라인 트랙 팬츠 - 알루미나 / JW0981", "루미나") is True
    )


def test_숫자포함_금지어도_경계적용():
    assert matches_forbidden("모델 A1234 상품", "A123") is False
    assert matches_forbidden("모델 A123 상품", "A123") is True


def test_하이픈_언더스코어는_경계로_본다():
    assert matches_forbidden("PUMA-GNC-TEE", "gnc") is True
    assert matches_forbidden("PUMA_GNC_TEE", "gnc") is True


def test_find_hit_는_목록순서를_따른다():
    words = ["없는말", "gnc", "푸마"]
    assert find_forbidden_hit("푸마 GNC 티셔츠", words) == "gnc"
    assert find_forbidden_hit("푸마 X GGNC 티셔츠", words) == "푸마"
    assert find_forbidden_hit("아디다스 티셔츠", words) is None


def test_빈값_방어():
    assert matches_forbidden("", "gnc") is False
    assert matches_forbidden("상품", "") is False
    assert find_forbidden_hit("", ["gnc"]) is None
