"""주문 상품명 → 모델코드(품번) 추출기.

운영DB 실측 근거 (최근 60일 samba_order.product_name, 2026-09-03):
  | 소싱처      | 총    | strict `[A-Z]{2,4}\\d[A-Z0-9]{5,9}` | loose `[A-Z]{1,4}\\d{3,}[A-Z0-9-]*` |
  |------------|------|------------------------------------|-------------------------------------|
  | MUSINSA    | 1087 | 317                                | 822                                 |
  | ABCmart    | 418  | 152                                | 373                                 |
  | LOTTEON    | 223  | 164                                | 188                                 |
  | GSShop     | 156  | 0                                  | 142                                 |
  | THEHYUNDAI | 76   | 9                                  | 67                                  |
  → strict 만으로는 30%대 커버리지. strict 우선 + loose 폴백 2단 추출이 필요하다.

strict 정규식은 order.py::_extract_product_code 와 동일 패턴이지만
그 함수는 카톡 품번 매칭 등 다른 경로가 쓰고 있어 건드리지 않고 여기 자체 구현한다.
"""

import re

# 1단: strict — YMM24377Z1 / DV0831085 형태 (order.py::_extract_product_code 동일 패턴)
_STRICT_RE = re.compile(r"[A-Z]{2,4}\d[A-Z0-9]{5,9}")

# 2단: loose — CW2288-111 / B75806 처럼 짧은 접두 + 숫자 3자리 이상 + 꼬리(하이픈 허용)
_LOOSE_RE = re.compile(r"(?:^|[^A-Z0-9])([A-Z]{1,4}\d{3,}[A-Z0-9-]*)(?:[^A-Z0-9]|$)")

# loose 오탐 제외 — 연도(19xx/20xx로만 이루어진 것)
_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")
# loose 오탐 제외 — 시즌코드(SS24/FW25/AW23 처럼 시즌 접두 + 2자리 숫자만)
_SEASON_RE = re.compile(r"^(?:SS|FW|AW)\d{2}$")


def normalize_code(s: str | None) -> str:
    """모델코드 비교용 정규화 — 대문자화 + 하이픈/공백 제거."""
    if not s:
        return ""
    return s.upper().replace("-", "").replace(" ", "")


def _is_false_positive(candidate: str) -> bool:
    """loose 후보의 오탐 여부 판정."""
    # 길이 5 미만 — 짧은 코드(SS24, B806 등)는 오매칭 위험이 크다
    if len(candidate) < 5:
        return True
    # 순수 숫자 — 사이즈(270)·수량 등
    if candidate.isdigit():
        return True
    # 연도(2024, 1998 등)로만 이루어진 것
    if _YEAR_RE.fullmatch(candidate):
        return True
    # 시즌코드(SS24/FW25/AW23) — 접두 + 2자리 숫자만인 것
    if _SEASON_RE.fullmatch(candidate):
        return True
    return False


def extract_model_code(product_name: str | None) -> str | None:
    """상품명에서 모델코드(품번)를 추출한다.

    1) strict `[A-Z]{2,4}\\d[A-Z0-9]{5,9}` 우선
    2) 실패 시 loose `(?:^|[^A-Z0-9])([A-Z]{1,4}\\d{3,}[A-Z0-9-]*)(?:[^A-Z0-9]|$)`
       — 단 연도/순수숫자/길이 5 미만/시즌코드 오탐 제외
    3) 둘 다 없으면 None (상품명 폴백 검색은 오매칭 위험이 커서 하지 않음)
    """
    if not product_name:
        return None
    text = product_name.upper()

    # 1단: strict
    m = _STRICT_RE.search(text)
    if m:
        return m.group(0)

    # 2단: loose — 앞에서부터 첫 유효 후보 채택
    for lm in _LOOSE_RE.finditer(text):
        candidate = lm.group(1).strip("-")
        if _is_false_positive(candidate):
            continue
        return candidate

    return None
