"""롯데ON itm 옵션 라벨 폴백 우선순위 회귀 테스트.

배경: 2026-04-26 LO2664562602 외 다수에서 itmNm/optNm 빈 문자열로 매칭 0건 →
stkQty=0 강제 → 전 옵션 SOUT_STK 자동 잠김. sitmNm 또는 itmOptLst[0].optVal에
실제 라벨이 있어 폴백 보강. codex 권고 회귀 테스트 + 안전성 케이스 추가.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.plugins.markets.lotteon import _pick_lotteon_itm_label


class TestPickLotteonItmLabel:
    def test_itmnm_present_wins(self) -> None:
        # 우선순위 1: itmNm 있으면 모든 후보 무시하고 itmNm 사용
        itm = {
            "itmNm": "230",
            "sitmNm": "240",
            "itmOptLst": [{"optVal": "250"}],
            "optNm": "사이즈",
        }
        assert _pick_lotteon_itm_label(itm) == "230"

    def test_blank_itmnm_falls_back_to_sitmnm(self) -> None:
        # 1D blank-label hotfix: itmNm="" → sitmNm 폴백 (LO2664562602 17/17 케이스)
        itm = {
            "itmNm": "",
            "sitmNm": "230",
            "itmOptLst": [{"optVal": "230"}],
            "optNm": "사이즈",
        }
        assert _pick_lotteon_itm_label(itm) == "230"

    def test_blank_itmnm_and_sitmnm_falls_back_to_optval(self) -> None:
        # itmNm="" sitmNm="" → optVal 폴백
        itm = {
            "itmNm": "",
            "sitmNm": "",
            "itmOptLst": [{"optVal": "230"}],
            "optNm": "사이즈",
        }
        assert _pick_lotteon_itm_label(itm) == "230"

    def test_whitespace_only_itmnm_hardening(self) -> None:
        # 공백 하드닝: itmNm=" " (공백 only) → sitmNm 폴백
        # 기존 ``or`` 체인은 " "을 truthy로 판단해 폴백 X. fix는 strip 후 비교.
        itm = {
            "itmNm": " ",
            "sitmNm": "230",
            "itmOptLst": [{"optVal": "230"}],
            "optNm": "사이즈",
        }
        assert _pick_lotteon_itm_label(itm) == "230"

    def test_optnm_is_last_fallback(self) -> None:
        # optNm은 축 이름("사이즈")이라 값이 아니므로 마지막 폴백
        itm = {
            "itmNm": "",
            "sitmNm": "",
            "itmOptLst": [{"optVal": ""}],
            "optNm": "사이즈",
        }
        assert _pick_lotteon_itm_label(itm) == "사이즈"

    def test_all_blank_returns_empty_string(self) -> None:
        # 모든 후보 비어있음 → 빈 문자열 (호출자가 매칭 실패로 처리)
        itm = {
            "itmNm": "",
            "sitmNm": "",
            "itmOptLst": [],
            "optNm": "",
        }
        assert _pick_lotteon_itm_label(itm) == ""

    def test_2d_combined_label_via_sitmnm(self) -> None:
        # 2D 옵션: sitmNm에 결합 라벨 "블랙 / 230"이 들어오는 케이스 (현재 매칭 가능 영역)
        itm = {
            "itmNm": "",
            "sitmNm": "블랙 / 230",
            "itmOptLst": [{"optVal": "230"}],
            "optNm": "사이즈",
        }
        assert _pick_lotteon_itm_label(itm) == "블랙 / 230"

    def test_none_values_skipped(self) -> None:
        # None 후보는 건너뛰고 다음으로 폴백
        itm = {
            "itmNm": None,
            "sitmNm": None,
            "itmOptLst": [{"optVal": "230"}],
            "optNm": None,
        }
        assert _pick_lotteon_itm_label(itm) == "230"

    def test_missing_keys_safe(self) -> None:
        # 키 자체 누락 시에도 KeyError 없이 폴백 동작
        itm = {"sitmNm": "230"}
        assert _pick_lotteon_itm_label(itm) == "230"

    def test_optlst_with_non_dict_first_element_safe(self) -> None:
        # itmOptLst[0]가 dict 아닌 이상 응답에도 KeyError 없이 다음으로 폴백
        itm = {
            "itmNm": "",
            "sitmNm": "",
            "itmOptLst": ["broken"],
            "optNm": "사이즈",
        }
        assert _pick_lotteon_itm_label(itm) == "사이즈"
