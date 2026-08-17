r"""금지어 매칭 — 영문/숫자 금지어에 단어 경계 적용.

금지어 매칭은 원래 전부 부분일치(`word.lower() in name.lower()`)였다. 한글 금지어는
그래야 맞지만("포켓몬" 이 "포켓몬스터" 를 잡아야 한다), 짧은 영문 금지어에서는
전혀 무관한 상품이 대량으로 막혔다. 2026-08-15 실측 오탐:

    금지어 'sex'  ← UNISEX PUMA X SAYSKY SS TEE            (7건)
    금지어 'TSI'  ← THINK OU(TSI)DE 퀵드라이 반팔티셔츠      (32건)
    금지어 'AMI'  ← GOCap SC - WWM 26 - Mi(ami) 마이애미     (16건)
    금지어 'JMW'  ← 위크론 지오 셔츠 JBW(JMW)ZH041 (품번)     (11건)
    금지어 'gnc'  ← 푸마 X G(GNC) 와일드플라워 티             (8건)

합계 74건이 전송에서 조용히 빠지고 있었다.

경계 문자를 ASCII 영숫자로 한정한 이유 — 파이썬 `\b` 는 유니코드 `\w` 기준이라
한글도 단어 문자로 본다. `\bsex\b` 는 "UNISEX" 를 안 잡는 대신 "정품sex상품" 도
못 잡는다. 여기서는 앞뒤가 ASCII 영숫자일 때만 매칭을 막으므로 한글에 둘러싸인
영문 금지어는 그대로 잡힌다.

한글 금지어는 부분일치를 유지한다. 한글에 단어 경계를 적용하면 조사가 붙은
"나이키를", 합성어 "포켓몬스터" 가 전부 빠져나간다. 그 대가로 '루미나' 가
아디다스 색상명 '알루미나' 를 잡는 오탐(28건)은 남는다 — 이건 매칭 방식이 아니라
금지어 목록에서 다룰 문제다.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable, Optional

# 영문/숫자로만 이루어진 금지어 — 단어 경계 대상
_ASCII_ONLY = re.compile(r"^[A-Za-z0-9]+$")


@lru_cache(maxsize=1024)
def _compiled(word: str) -> Optional[re.Pattern]:
    """영문/숫자 금지어면 경계 정규식, 그 외(한글 등)는 None(부분일치 유지)."""
    if not _ASCII_ONLY.match(word):
        return None
    return re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


def matches_forbidden(haystack: str, word: str) -> bool:
    """금지어 하나가 문자열에 걸리는지."""
    if not word or not haystack:
        return False
    pattern = _compiled(word)
    if pattern is not None:
        return pattern.search(haystack) is not None
    return word.lower() in haystack.lower()


def find_forbidden_hit(haystack: str, words: Iterable[str]) -> Optional[str]:
    """걸린 금지어 하나를 돌려준다. 없으면 None. 목록 순서를 따른다."""
    if not haystack:
        return None
    for word in words:
        if matches_forbidden(haystack, word):
            return word
    return None
