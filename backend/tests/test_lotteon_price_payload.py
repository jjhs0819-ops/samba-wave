"""롯데ON 수정 후 가격 동기화 헬퍼 회귀 테스트.

배경: update_product API는 spd 헤더만 반영하고 itm 가격(slPrc)은 무시한다.
일반 수정 경로(plugins/markets/lotteon.py:~1685)에서 update_price를 호출하지
않아 sale_price 변경이 셀러 페이지에 반영되지 않는 사고 발생. 경량 분기는
이미 update_price를 호출하므로 같은 패턴으로 보강.

`_build_lotteon_price_payload`는 saved itmLst (transform_product 결과)와
target itmLst (get_product 응답)를 매칭해 update_price 페이로드를 만든다.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.plugins.markets.lotteon import _build_lotteon_price_payload


SPD = "LO2664497364"


class TestBuildLotteonPricePayload:
    def test_normal_1d_match_by_optval(self) -> None:
        # 정상 케이스: 1D 옵션, optVal 매칭으로 새 slPrc 반영
        saved = [
            {"itmOptLst": [{"optVal": "230"}], "slPrc": 75900},
            {"itmOptLst": [{"optVal": "240"}], "slPrc": 75900},
        ]
        target = [
            {"sitmNo": "LO_001", "itmOptLst": [{"optVal": "230"}]},
            {"sitmNo": "LO_002", "itmOptLst": [{"optVal": "240"}]},
        ]
        result = _build_lotteon_price_payload(saved, target, SPD)
        assert result == [
            {"sitmNo": "LO_001", "spdNo": SPD, "slPrc": 75900},
            {"sitmNo": "LO_002", "spdNo": SPD, "slPrc": 75900},
        ]

    def test_optval_mismatch_skips_to_avoid_wrong_variant(self) -> None:
        # codex P1: 옵션 매칭 실패 시 스킵 — 다른 variant 가격으로 silently 덮어쓰기 방지
        saved = [
            {"itmOptLst": [{"optVal": "230"}], "slPrc": 75900},
        ]
        target = [
            {"sitmNo": "LO_001", "itmOptLst": [{"optVal": "999"}]},  # 매칭 X
        ]
        result = _build_lotteon_price_payload(saved, target, SPD)
        assert result == []

    def test_empty_saved_returns_empty(self) -> None:
        # saved 비어있으면 default_slprc=0 → 모두 스킵
        result = _build_lotteon_price_payload(
            [], [{"sitmNo": "LO_001", "itmOptLst": [{"optVal": "230"}]}], SPD
        )
        assert result == []

    def test_empty_target_returns_empty(self) -> None:
        # target 비어있으면 빈 리스트
        saved = [{"itmOptLst": [{"optVal": "230"}], "slPrc": 75900}]
        result = _build_lotteon_price_payload(saved, [], SPD)
        assert result == []

    def test_zero_slprc_in_saved_skips_unmatched(self) -> None:
        # saved에 slPrc=0인 옵션 → 매핑 미생성, 매칭 실패 시 스킵 (다른 variant 덮어쓰기 방지)
        saved = [
            {"itmOptLst": [{"optVal": "230"}], "slPrc": 0},
            {"itmOptLst": [{"optVal": "240"}], "slPrc": 75900},
        ]
        target = [
            {"sitmNo": "LO_001", "itmOptLst": [{"optVal": "230"}]},
        ]
        # '230'은 매핑 X → 매칭 실패 → 스킵 (240의 75900으로 silently 덮지 않음)
        result = _build_lotteon_price_payload(saved, target, SPD)
        assert result == []

    def test_target_without_sitmno_skipped(self) -> None:
        # sitmNo / itmNo 둘 다 없는 itm은 스킵
        saved = [{"itmOptLst": [{"optVal": "230"}], "slPrc": 75900}]
        target = [
            {"itmOptLst": [{"optVal": "230"}]},  # sitmNo 없음
            {"sitmNo": "LO_002", "itmOptLst": [{"optVal": "230"}]},
        ]
        result = _build_lotteon_price_payload(saved, target, SPD)
        assert result == [{"sitmNo": "LO_002", "spdNo": SPD, "slPrc": 75900}]

    def test_target_without_optlst_uses_default(self) -> None:
        # itmOptLst 비어있는 단품(옵션 없음) → optVal="" → default_slprc 사용
        saved = [{"itmOptLst": [{"optVal": "default"}], "slPrc": 75900}]
        target = [{"sitmNo": "LO_001", "itmOptLst": []}]
        result = _build_lotteon_price_payload(saved, target, SPD)
        assert result == [{"sitmNo": "LO_001", "spdNo": SPD, "slPrc": 75900}]

    def test_multiple_prices_per_option(self) -> None:
        # 옵션마다 가격이 다른 경우 (드물지만 가능)
        saved = [
            {"itmOptLst": [{"optVal": "230"}], "slPrc": 50000},
            {"itmOptLst": [{"optVal": "240"}], "slPrc": 60000},
        ]
        target = [
            {"sitmNo": "LO_001", "itmOptLst": [{"optVal": "230"}]},
            {"sitmNo": "LO_002", "itmOptLst": [{"optVal": "240"}]},
        ]
        result = _build_lotteon_price_payload(saved, target, SPD)
        assert result == [
            {"sitmNo": "LO_001", "spdNo": SPD, "slPrc": 50000},
            {"sitmNo": "LO_002", "spdNo": SPD, "slPrc": 60000},
        ]

    def test_non_dict_optlst_first_safe(self) -> None:
        # itmOptLst[0]가 dict 아닌 이상 응답 — opt_val 매칭 실패해도 fallback_slprc로 처리
        # (codex P1 fix 후: 가격 동기화 우선, opt_val 못 만들어도 slPrc는 보냄)
        saved = [{"itmOptLst": ["broken"], "slPrc": 75900}]
        target = [{"sitmNo": "LO_001", "itmOptLst": ["broken"]}]
        result = _build_lotteon_price_payload(saved, target, SPD)
        assert result == [{"sitmNo": "LO_001", "spdNo": SPD, "slPrc": 75900}]

    def test_string_slprc_coerced_to_int(self) -> None:
        # saved의 slPrc가 문자열이어도 int 변환
        saved = [{"itmOptLst": [{"optVal": "230"}], "slPrc": "75900"}]
        target = [{"sitmNo": "LO_001", "itmOptLst": [{"optVal": "230"}]}]
        result = _build_lotteon_price_payload(saved, target, SPD)
        assert result == [{"sitmNo": "LO_001", "spdNo": SPD, "slPrc": 75900}]

    def test_invalid_slprc_treated_as_zero(self) -> None:
        # slPrc가 숫자로 변환 불가 (예: None, 'abc') → 0으로 처리, 매칭 실패 시 스킵
        saved = [
            {"itmOptLst": [{"optVal": "230"}], "slPrc": "abc"},
            {"itmOptLst": [{"optVal": "240"}], "slPrc": 75900},
        ]
        target = [
            {"sitmNo": "LO_001", "itmOptLst": [{"optVal": "230"}]},  # 매칭 X → 스킵
        ]
        result = _build_lotteon_price_payload(saved, target, SPD)
        assert result == []

    def test_itmno_fallback_when_no_sitmno(self) -> None:
        # sitmNo 없으면 itmNo 사용
        saved = [{"itmOptLst": [{"optVal": "230"}], "slPrc": 75900}]
        target = [{"itmNo": "LO_OLD_001", "itmOptLst": [{"optVal": "230"}]}]
        result = _build_lotteon_price_payload(saved, target, SPD)
        assert result == [{"sitmNo": "LO_OLD_001", "spdNo": SPD, "slPrc": 75900}]

    def test_single_sku_no_itmoptlst(self) -> None:
        # codex P1 케이스: 옵션 없는 단품 (transform_product가 itmOptLst 생략)
        # saved/target 모두 itmOptLst 없음 → fallback_slprc로 동작해야 함
        saved = [{"slPrc": 56100}]  # itmOptLst 키 없음
        target = [{"sitmNo": "LO_SINGLE_001"}]  # itmOptLst 키 없음
        result = _build_lotteon_price_payload(saved, target, SPD)
        assert result == [{"sitmNo": "LO_SINGLE_001", "spdNo": SPD, "slPrc": 56100}]

    def test_single_sku_empty_itmoptlst(self) -> None:
        # itmOptLst가 빈 리스트인 케이스도 단품으로 처리되어야 함
        saved = [{"itmOptLst": [], "slPrc": 56100}]
        target = [{"sitmNo": "LO_SINGLE_002", "itmOptLst": []}]
        result = _build_lotteon_price_payload(saved, target, SPD)
        assert result == [{"sitmNo": "LO_SINGLE_002", "spdNo": SPD, "slPrc": 56100}]

    def test_optval_normalization_slash_spacing(self) -> None:
        # codex P1 fix: optVal 정규화 — "240 / Beige" vs "240/Beige" 같은 포맷 차이 흡수
        saved = [
            {"itmOptLst": [{"optVal": "240 / Beige"}], "slPrc": 50000},
            {"itmOptLst": [{"optVal": "240 / Black"}], "slPrc": 60000},
        ]
        target = [
            {
                "sitmNo": "LO_001",
                "itmOptLst": [{"optVal": "240/Beige"}],
            },  # 슬래시 공백 X
            {
                "sitmNo": "LO_002",
                "itmOptLst": [{"optVal": "240 /Black"}],
            },  # 한쪽만 공백
        ]
        result = _build_lotteon_price_payload(saved, target, SPD)
        # 정규화로 둘 다 매칭되어야 함 (Beige=50000, Black=60000)
        assert result == [
            {"sitmNo": "LO_001", "spdNo": SPD, "slPrc": 50000},
            {"sitmNo": "LO_002", "spdNo": SPD, "slPrc": 60000},
        ]

    def test_optval_normalization_multiple_spaces(self) -> None:
        # 다중 공백도 단일 공백으로 정규화
        saved = [{"itmOptLst": [{"optVal": "L  XL"}], "slPrc": 50000}]
        target = [{"sitmNo": "LO_001", "itmOptLst": [{"optVal": "L XL"}]}]
        result = _build_lotteon_price_payload(saved, target, SPD)
        assert result == [{"sitmNo": "LO_001", "spdNo": SPD, "slPrc": 50000}]

    def test_no_silent_fallback_to_other_variant(self) -> None:
        # codex P1 핵심 — 한 variant 매칭 실패 시 다른 variant의 더 비싼 가격으로
        # silently 덮어쓰면 안 됨. 매칭 실패는 명시적 스킵.
        saved = [
            {"itmOptLst": [{"optVal": "S"}], "slPrc": 30000},
            {"itmOptLst": [{"optVal": "M"}], "slPrc": 40000},
            {"itmOptLst": [{"optVal": "L"}], "slPrc": 50000},  # 가장 비싼 variant
        ]
        target = [
            {"sitmNo": "LO_001", "itmOptLst": [{"optVal": "XL"}]},  # saved에 없는 옵션
        ]
        result = _build_lotteon_price_payload(saved, target, SPD)
        # XL을 L의 50000으로 덮으면 안 됨 → 스킵
        assert result == []

    def test_options_target_with_no_option_saved_skipped(self) -> None:
        # saved 단품(slPrc만) + target 옵션 있는 itm → 매칭 실패 → 스킵
        # (saved와 target의 형태 불일치는 의도치 않은 가격 덮어쓰기 방지를 위해 스킵)
        saved = [{"slPrc": 56100}]
        target = [
            {"sitmNo": "LO_001", "itmOptLst": [{"optVal": "230"}]},
            {"sitmNo": "LO_002", "itmOptLst": [{"optVal": "240"}]},
        ]
        result = _build_lotteon_price_payload(saved, target, SPD)
        assert result == []
