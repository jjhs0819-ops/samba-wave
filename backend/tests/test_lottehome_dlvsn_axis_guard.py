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
    """_lh_valid_dlvsn — 행 생성용 단건 검증 (+자릿수 축 판별, 7/29 109건 실사고)."""

    def setup_method(self) -> None:
        self.detail: dict = {}
        self.fn = _load(
            {"_lh_bsn_ok", "_lh_valid_dlvsn"}, {"_lh_detail_axis": self.detail}
        )["_lh_valid_dlvsn"]

    def test_valid_value_passes(self) -> None:
        self.detail["AA"] = {"914000001"}
        assert (
            self.fn("AA", {"DlvUnitSn": "1130000001", "OrdDtlSn": "914000001"})
            == "1130000001"
        )

    def test_known_detail_axis_value_rejected(self) -> None:
        self.detail["AA"] = {"914000001"}
        assert self.fn("AA", {"DlvUnitSn": "914000001"}) == ""

    def test_same_value_as_own_detail_field_rejected(self) -> None:
        """맵 학습 전이라도 자기 행에서 양축 값이 같으면 혼입."""
        assert (
            self.fn("AA", {"DlvUnitSn": "914000001", "OrgOrdDtlSn": "914000001"}) == ""
        )

    def test_nine_digit_rejected_without_cross_evidence(self) -> None:
        """교차 증거가 없어도 9자리(상세축 시퀀스)는 배송축으로 인정하지 않는다.

        2026-07-29 실사고: DlvUnitSn 필드에 상세축 값만 달랑 오는 응답은
        교차 증거 기반 가드(#689)를 통과해 109건이 잘못된 키로 생성됐다.
        """
        assert self.fn("AA", {"DlvUnitSn": "914736467"}) == ""

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

    def test_multi_line_new_order_marks_lh_multi(self) -> None:
        """신규주문 list-ProdInfo 경로는 파서에 합배송 플래그를 넘겨야 한다.

        빠지면 주문 단위 값인 SubOrdNo 가 모든 라인의 키가 되어
        _lh_seen 중복제거에 첫 라인만 남고 나머지 라인이 통째로 소실된다.
        """
        idx = self.src.find("for _i, _prod in enumerate(_prod_info_raw):")
        assert idx != -1
        block = self.src[idx : idx + 800]
        assert '_flat["_lh_multi"]' in block, (
            "합배송 플래그 누락 — SubOrdNo 승격이 라인 구분을 뭉갠다"
        )

    def test_sub_ord_no_path_registers_old_key(self) -> None:
        """SubOrdNo 승격으로 키가 바뀌면 옛 키 레코드를 삭제 대상에 넣어야 한다."""
        idx = self.src.find("_has_sub = _lh_bsn_ok(_sub_sn)")
        assert idx != -1
        block = self.src[idx : idx + 2800]
        assert "_lh_replaced_old_keys.append" in block, (
            "옛 상세축 키 레코드를 안 지우면 같은 주문이 두 행으로 남는다"
        )


class TestOrderKeyMirrorsParser:
    """_lh_order_key — 파서 키 산출과 동일해야 한다.

    어긋나면 _lh_seen 에 담기는 값과 실제 저장 키가 달라져 배송조회 경로에서
    같은 주문이 중복 행으로 들어온다.
    """

    def setup_method(self) -> None:
        self.fn = _load({"_lh_bsn_ok", "_lh_order_key"}, {})["_lh_order_key"]

    def test_sub_ord_no_promoted(self) -> None:
        assert (
            self.fn(
                {
                    "OrdNo": "A1",
                    "SubOrdNo": "1130815689",
                    "ProdInfo": {"OrdDtlSn": "914736467"},
                }
            )
            == "A1:1130815689"
        )

    def test_dlvunitsn_wins_over_sub_ord_no(self) -> None:
        assert (
            self.fn(
                {
                    "OrdNo": "A1",
                    "SubOrdNo": "1130815689",
                    "ProdInfo": {"DlvUnitSn": "1130999999"},
                }
            )
            == "A1:1130999999"
        )

    def test_multi_keeps_old_chain(self) -> None:
        assert (
            self.fn(
                {
                    "OrdNo": "A1",
                    "SubOrdNo": "1130815689",
                    "_lh_multi": True,
                    "ProdInfo": {"OrdDtlSn": "914736467"},
                }
            )
            == "A1:914736467"
        )

    def test_short_sub_ord_no_not_promoted(self) -> None:
        assert (
            self.fn(
                {
                    "OrdNo": "A1",
                    "SubOrdNo": "12345",
                    "ProdInfo": {"OrdDtlSn": "914736467"},
                }
            )
            == "A1:914736467"
        )


class TestParserSubOrdNoKey:
    """_parse_lottehome_order — 배송축 승격 키 산출 (공식 스펙 SubOrdNo)."""

    def setup_method(self) -> None:
        import logging

        self.fn = _load(
            {"_parse_lottehome_order"}, {"logger": logging.getLogger("test_lh")}
        )["_parse_lottehome_order"]

    def _key(self, item: dict) -> str:
        return str(self.fn(item, "cid", "라벨").get("order_number", ""))

    def test_sub_ord_no_promoted_over_detail_axis(self) -> None:
        """상세축(9자리)만 있는 신규주문도 SubOrdNo(10자리)로 등록된다."""
        assert (
            self._key(
                {
                    "OrdNo": "A1",
                    "SubOrdNo": "1130815689",
                    "ProdInfo": {"OrdDtlSn": "914736467"},
                }
            )
            == "A1:1130815689"
        )

    def test_line_dlvunitsn_takes_priority(self) -> None:
        """라인별 검증값(DlvUnitSn)이 주문 단위 SubOrdNo 보다 정확하다."""
        assert (
            self._key(
                {
                    "OrdNo": "A1",
                    "SubOrdNo": "1130815689",
                    "ProdInfo": {"DlvUnitSn": "1130999999", "OrdDtlSn": "914736467"},
                }
            )
            == "A1:1130999999"
        )

    def test_multi_line_keeps_old_chain(self) -> None:
        """합배송은 SubOrdNo 가 라인 구분을 못 하므로 승격 금지 (라인 소실 방지)."""
        assert (
            self._key(
                {
                    "OrdNo": "A1",
                    "SubOrdNo": "1130815689",
                    "_lh_multi": True,
                    "ProdInfo": {"OrdDtlSn": "914736467"},
                }
            )
            == "A1:914736467"
        )

    def test_short_sub_ord_no_ignored(self) -> None:
        """10자리 미만은 배송축이 아니므로 승격하지 않는다."""
        assert (
            self._key(
                {
                    "OrdNo": "A1",
                    "SubOrdNo": "12345",
                    "ProdInfo": {"OrdDtlSn": "914736467"},
                }
            )
            == "A1:914736467"
        )

    def test_claim_path_unaffected(self) -> None:
        """취소/반품 경로(prefer_org_dtl_sn)는 원주문 매칭용 상세축을 유지한다."""
        parsed = self.fn(
            {
                "OrdNo": "A1",
                "SubOrdNo": "1130815689",
                "ProdInfo": {"OrgOrdDtlSn": "914736467", "OrdDtlSn": "914999999"},
            },
            "cid",
            "라벨",
            prefer_org_dtl_sn=True,
        )
        assert parsed.get("order_number") == "A1:914736467"
