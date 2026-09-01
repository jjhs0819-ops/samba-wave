"""Brand Risk System — normalize_alias_key() 단위 테스트 (DB 불필요).

핵심 검증:
1. ARC`TERYX / ARC'TERYX / ARC'TERYX(컬리) / ARC TERYX 가 같은 alias_key 로 묶임
   (2026-08 데이터 감사에서 확인된 실제 표기 오타 — ARC`TERYX 가
   samba_forbidden_word 에 백틱으로 잘못 등록돼 있었다)
2. PUMA vs PUMA BODYWEAR, SNOW PEAK vs SNOW PEAK APPAREL, NEW BALANCE vs
   NEW BALANCE KIDS 는 절대 합쳐지면 안 됨 — 실제 단어가 다르면 특수문자
   치환만으로는 합쳐지지 않는다는 걸 확인한다.
3. 기존 brand/model.py 의 normalize_brand() 는 이 Phase에서 변경하지
   않았다는 걸 회귀로 고정한다 — BrandGuardService.check() 동작 불변 보장.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.brand.alias_model import normalize_alias_key
from backend.domain.samba.brand.model import normalize_brand


class TestNormalizeAliasKeyApostropheVariants:
    """ARC`TERYX 표기변형 통합 — 실사례(2026-08 데이터 감사) 회귀 테스트."""

    def test_backtick_and_apostrophe_variants_converge(self) -> None:
        variants = [
            "ARC`TERYX",  # 백틱 — 실제 forbidden_word 등록값(오타)
            "ARC'TERYX",  # 정식 아포스트로피
            "ARC’TERYX",  # 컬리 쿼트(’)
            "ARC TERYX",  # 공백으로 대체된 경우
            "arc'teryx",  # 소문자
        ]
        keys = {normalize_alias_key(v) for v in variants}
        assert len(keys) == 1, f"같은 브랜드가 서로 다른 키로 갈라짐: {keys}"

    def test_converged_key_has_no_apostrophe_or_space(self) -> None:
        key = normalize_alias_key("ARC`TERYX")
        assert key == "arcteryx"

    def test_legacy_normalize_brand_unchanged(self) -> None:
        """brand/model.py 의 normalize_brand() 는 이번 Phase에서 손대지 않았다.

        기존 함수는 아포스트로피를 지우지 않으므로 ARC`TERYX 와 ARC'TERYX 가
        여전히 다른 키로 남아야 한다 — BrandGuardService.check() 의 기존
        동작(백틱 표기와 아포스트로피 표기를 다른 브랜드로 취급)이 이번
        Phase 로 인해 바뀌지 않았음을 고정한다.
        """
        assert normalize_brand("ARC`TERYX") != normalize_brand("ARC'TERYX")


class TestNormalizeAliasKeyPreservesProductLines:
    """실제 단어가 다른 상품군/라이선스는 절대 합치지 않는다."""

    def test_puma_vs_puma_bodywear_stay_distinct(self) -> None:
        assert normalize_alias_key("PUMA") != normalize_alias_key("PUMA BODYWEAR")

    def test_snow_peak_vs_apparel_stay_distinct(self) -> None:
        assert normalize_alias_key("SNOW PEAK") != normalize_alias_key(
            "SNOW PEAK APPAREL"
        )

    def test_new_balance_vs_kids_stay_distinct(self) -> None:
        assert normalize_alias_key("NEW BALANCE") != normalize_alias_key(
            "NEW BALANCE KIDS"
        )

    def test_apostrophe_stripping_does_not_merge_different_words(self) -> None:
        # 아포스트로피를 지워도 BODYWEAR 라는 실제 단어 자체는 그대로 남는다
        assert normalize_alias_key("PUMA'S") != normalize_alias_key("PUMA BODYWEAR")


class TestNormalizeAliasKeyBasics:
    def test_empty_string_returns_empty(self) -> None:
        assert normalize_alias_key("") == ""
        assert normalize_alias_key(None) == ""  # type: ignore[arg-type]

    def test_whitespace_and_case_normalized(self) -> None:
        assert normalize_alias_key("  Nike  ") == normalize_alias_key("nike")

    def test_distribution_suffix_stripped_same_as_legacy(self) -> None:
        # normalize_brand() 가 이미 하는 "(백화점)" 등 유통 접미사 제거를
        # normalize_alias_key() 도 그대로 물려받는다(중복 구현 안 함).
        assert normalize_alias_key("데상트(백화점)") == normalize_alias_key("데상트")
