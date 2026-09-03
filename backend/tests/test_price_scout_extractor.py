"""price_scout.extractor — 모델코드 추출 단위 테스트 (DB 불필요).

운영DB 실측(최근 60일)에서 strict 만으로는 30%대 커버리지라
strict 우선 + loose 폴백 2단 추출이 맞는지, 그리고 loose 오탐 제외
(연도/순수숫자/길이 5 미만/시즌코드)가 동작하는지 고정한다.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.price_scout.extractor import (
    extract_model_code,
    normalize_code,
)


class TestStrictExtraction:
    """1단 strict `[A-Z]{2,4}\\d[A-Z0-9]{5,9}` — order.py 기존 패턴과 동일."""

    def test_ymm_style_code(self) -> None:
        # 전형적인 strict 매칭 품번
        assert extract_model_code("K-스윙 반팔 티셔츠 YMM24377Z1 블랙") == "YMM24377Z1"

    def test_strict_beats_loose(self) -> None:
        # strict 매칭이 있으면 loose 후보보다 우선
        assert extract_model_code("아디다스 DV0831085 (B75806)") == "DV0831085"


class TestLooseFallback:
    """2단 loose — 하이픈 품번·짧은 접두 품번 폴백."""

    def test_nike_hyphen_code(self) -> None:
        # 나이키 형식(CW2288-111)은 strict 불충족(하이픈) → loose 로 잡혀야 함
        assert extract_model_code("나이키 에어포스1 07 CW2288-111") == "CW2288-111"

    def test_adidas_single_letter_prefix(self) -> None:
        # 접두 1글자(B75806)는 strict([A-Z]{2,4}) 불충족 → loose 로 잡혀야 함
        assert extract_model_code("아디다스 삼바 OG B75806") == "B75806"


class TestFalsePositiveRejection:
    """loose 오탐 제외 — 사이즈/연도/시즌코드는 품번이 아니다."""

    def test_pure_number_size(self) -> None:
        # 순수 숫자(사이즈 270)
        assert extract_model_code("270") is None

    def test_year_only(self) -> None:
        # 연도(2024)
        assert extract_model_code("2024 신상") is None

    def test_season_code(self) -> None:
        # 시즌코드(SS24)
        assert extract_model_code("SS24") is None

    def test_season_code_in_name(self) -> None:
        # 상품명 속 시즌코드도 품번으로 오인하면 안 됨
        assert extract_model_code("FW25 겨울 신상 패딩") is None

    def test_short_candidate_rejected(self) -> None:
        # 길이 5 미만 후보 (A123)
        assert extract_model_code("에코백 A123") is None

    def test_none_and_empty(self) -> None:
        assert extract_model_code(None) is None
        assert extract_model_code("") is None
        assert extract_model_code("나이키 에어포스") is None


class TestNormalizeCode:
    """비교용 정규화 — 대문자화 + 하이픈/공백 제거."""

    def test_normalize(self) -> None:
        assert normalize_code("cw2288-111") == "CW2288111"
        assert normalize_code("CW 2288 111") == "CW2288111"
        assert normalize_code(None) == ""

    def test_normalized_match_roundtrip(self) -> None:
        # 추출 → 정규화 → 상품명 정규화본에 포함 (service 매칭 로직의 전제)
        name = "나이키 에어포스1 07 CW2288-111"
        code = extract_model_code(name)
        assert code is not None
        assert normalize_code(code) in normalize_code(name)
