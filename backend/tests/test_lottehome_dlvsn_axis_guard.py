"""롯데홈 DlvUnitSn 값 축 검증 + 합배송 인덱스 정합성 회귀 테스트 (#689 후속).

배경:
  #689 는 롯데홈이 DlvUnitSn "필드"에 주문상세 축 값을 섞어 주는 사이클을 막으려고
  `_lh_clean_dlvsns` 로 혼입 값을 걸러냈다. 그런데 호출부는 그 목록을 **상품 인덱스**
  로 참조한다(`_dlvsn_list[_i]`). 목록이 부분적으로 짧아지면
    - 뒤 상품에 남의 배송단위 번호가 붙거나
    - `else: _flat["_lh_prod_idx"] = _i` 인덱스 폴백으로 새어
      옛 "인덱스 형식 키" 사고(취소·송장전송 불가 행)가 재유입된다.

fix:
  부분 제거가 발생하면 목록을 통째로 비워 그 주문을 이번 사이클 보류시킨다.
  추가로 상품 수 > DlvUnitSn 수 인 경우도 보류(인덱스 매핑 불성립).
  둘 다 기존 "추측 키 금지 → 다음 정상 사이클에 등록" 기제를 그대로 탄다.
"""

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ORDER_PY = BACKEND_ROOT / "backend/api/v1/routers/samba/order.py"


def _load(names: set[str], ns_extra: dict) -> dict:
    """중첩 함수만 AST 로 떼어 최상위 exec — 자유변수는 ns_extra 로 주입."""
    tree = ast.parse(ORDER_PY.read_text(encoding="utf-8"))
    found = [
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in names
    ]
    assert {f.name for f in found} == names, "대상 중첩 함수 누락"
    mod = ast.Module(body=found, type_ignores=[])
    ast.fix_missing_locations(mod)
    ns: dict = dict(ns_extra)
    exec(compile(mod, "<isolated>", "exec"), ns)
    return ns


class TestCleanDlvsns:
    """_lh_clean_dlvsns — 부분 제거는 전량 보류."""

    def setup_method(self) -> None:
        self.detail: dict = {}
        self.dlvsn: dict = {}
        self.mixed: set = set()
        self.fn = _load(
            {"_lh_clean_dlvsns"},
            {
                "_lh_detail_axis": self.detail,
                "_lh_dlvsn_map": self.dlvsn,
                "_lh_axis_mixed": self.mixed,
            },
        )["_lh_clean_dlvsns"]

    def test_clean_passthrough(self) -> None:
        """혼입 없으면 순서 그대로 반환."""
        self.dlvsn["AA"] = ["1130001", "1130002", "1130003"]
        self.detail["AA"] = {"914001", "914002"}
        assert self.fn("AA") == ["1130001", "1130002", "1130003"]
        assert self.mixed == set()

    def test_partial_mix_defers_whole_order(self) -> None:
        """1개만 혼입돼도 전량 보류 — 인덱스 밀림 방지 (핵심 회귀)."""
        self.dlvsn["AA"] = ["1130001", "914002", "1130003"]
        self.detail["AA"] = {"914002"}
        assert self.fn("AA") == [], "부분 제거를 그대로 돌려주면 인덱스가 밀린다"
        assert "AA" in self.mixed

    def test_extra_detail_of_current_row_counts(self) -> None:
        """맵에 아직 없는 현재 행의 상세축 값도 혼입 판정에 쓴다."""
        self.dlvsn["AA"] = ["1130001", "914009"]
        assert self.fn("AA", {"OrgOrdDtlSn": "914009"}) == []
        assert "AA" in self.mixed

    def test_all_mixed_returns_empty(self) -> None:
        self.dlvsn["AA"] = ["914001"]
        self.detail["AA"] = {"914001"}
        assert self.fn("AA") == []

    def test_unknown_order_returns_empty_without_flagging(self) -> None:
        """수집된 DlvUnitSn 자체가 없는 주문은 혼입이 아니라 미확보."""
        assert self.fn("ZZ") == []
        assert self.mixed == set()


class TestValidDlvsn:
    """_lh_valid_dlvsn — 행 생성용 단건 검증."""

    def setup_method(self) -> None:
        self.detail: dict = {}
        self.fn = _load({"_lh_valid_dlvsn"}, {"_lh_detail_axis": self.detail})[
            "_lh_valid_dlvsn"
        ]

    def test_valid_value_passes(self) -> None:
        self.detail["AA"] = {"914001"}
        assert (
            self.fn("AA", {"DlvUnitSn": "1130001", "OrdDtlSn": "914001"}) == "1130001"
        )

    def test_known_detail_axis_value_rejected(self) -> None:
        self.detail["AA"] = {"914001"}
        assert self.fn("AA", {"DlvUnitSn": "914001"}) == ""

    def test_same_value_as_own_detail_field_rejected(self) -> None:
        """맵 학습 전이라도 자기 행에서 양축 값이 같으면 혼입."""
        assert self.fn("AA", {"DlvUnitSn": "914001", "OrgOrdDtlSn": "914001"}) == ""

    def test_missing_value(self) -> None:
        assert self.fn("AA", {}) == ""


class TestCallSiteGuards:
    """호출부 정적 계약 — 인덱스 매핑 불성립 시 보류."""

    def setup_method(self) -> None:
        self.src = ORDER_PY.read_text(encoding="utf-8")

    def test_prod_count_vs_dlvsn_count_guard(self) -> None:
        idx = self.src.find("_dlvsn_list = _lh_clean_dlvsns(_no_key)")
        assert idx != -1
        block = self.src[idx : idx + 1200]
        assert "len(_dlvsn_list) <" in block, (
            "상품 수 > DlvUnitSn 수 인데 보류하지 않으면 뒤 상품이 인덱스 키로 샌다"
        )

    def test_axis_mixed_logged(self) -> None:
        assert "상세축 혼입 감지" in self.src, (
            "혼입 보류가 로그에 안 남으면 오판(정상 주문 영구 보류)을 못 잡는다"
        )
