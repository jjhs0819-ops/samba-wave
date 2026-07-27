"""롯데홈쇼핑 이축(OrdDtlSn↔DlvUnitSn) 교차 매칭 회귀 테스트 (issue #688).

배경:
  롯데홈 OpenAPI 는 한 주문에 식별자 축이 2개다.
    - 배송단위 축: 신규주문 SubOrdNo == 배송조회 DlvUnitSn (원본 행 저장 키)
    - 주문상세 축: 신규주문 OrgOrdDtlSn/ProdSeq == 배송조회 OrdDtlSn
  취소/반품 경로는 #528/#393 fix 로 prefer_org_dtl_sn=True (주문상세 축) 키를
  합성하는데, 원본 행은 #216 fix 로 배송단위 축(DlvUnitSn) 키로 저장돼 있다.
  → DB 매칭 실패 → 유령 취소행 INSERT + 원본 행은 pending 잔존(취소 미반영).
  유령 정리 SQL 은 status='pending' 만 지우므로 취소 유령(status=cancelled)은
  청소되지도 않는다 → 취소된 주문을 발주할 위험.

fix:
  클레임 응답의 OrgDlvUnitSn(원 배송단위 번호)을 alt 키로 등록하고,
  _existing_id_map 빌드 뒤 2차 역조회로 원본 행을 찾아 UPDATE 경로로 되돌린다.
  재발급 DlvUnitSn 은 오매칭 위험이라 alt 후보에서 제외한다.

테스트:
  헬퍼 2개는 AST 격리 실행으로 동작 검증(order.py 는 순환 import 라 직접 import 불가),
  호출부·2차 역조회 가드는 소스 정적 계약 가드.
"""

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ORDER_PY = BACKEND_ROOT / "backend/api/v1/routers/samba/order.py"


def _load_nested_funcs(names: set[str], ns_extra: dict) -> dict:
    """order.py 안 중첩 함수만 AST 로 떼어 최상위에서 exec.

    중첩 함수의 자유변수(_lh_alt_key_map 등)는 최상위 exec 시 전역 조회가 되므로
    ns_extra 로 주입해 동작을 그대로 검증할 수 있다.
    """
    tree = ast.parse(ORDER_PY.read_text(encoding="utf-8"))
    found = [
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names
    ]
    assert {f.name for f in found} == names, (
        f"대상 중첩 함수 누락: {names - {f.name for f in found}}"
    )
    mod = ast.Module(
        body=[ast.FunctionDef(**{**f.__dict__}) for f in found], type_ignores=[]
    )
    ast.fix_missing_locations(mod)
    ns: dict = dict(ns_extra)
    exec(compile(mod, "<isolated>", "exec"), ns)
    return ns


class TestNormProds:
    """_lh_norm_prods — _parse_lottehome_order_multi 와 동일한 정규화."""

    def setup_method(self) -> None:
        self.ns = _load_nested_funcs({"_lh_norm_prods", "_lh_reg_alt_keys"}, {})
        self.fn = self.ns["_lh_norm_prods"]

    def test_dict_to_list(self) -> None:
        assert self.fn({"ProdInfo": {"A": 1}}) == [{"A": 1}]

    def test_empty_to_single_blank(self) -> None:
        assert self.fn({"ProdInfo": []}) == [{}]
        assert self.fn({}) == [{}]

    def test_non_dict_items_blanked(self) -> None:
        # 인덱스가 밀리면 alt 키가 다른 상품에 붙는다 → 자리 유지 필수
        assert self.fn({"ProdInfo": [{"A": 1}, "junk", {"B": 2}]}) == [
            {"A": 1},
            {},
            {"B": 2},
        ]


class TestRegAltKeys:
    """_lh_reg_alt_keys — 클레임 행의 반대 축(배송단위) 후보 키 등록."""

    def setup_method(self) -> None:
        self.alt_map: dict = {}
        self.ns = _load_nested_funcs(
            {"_lh_norm_prods", "_lh_reg_alt_keys"},
            {"_lh_alt_key_map": self.alt_map},
        )
        self.fn = self.ns["_lh_reg_alt_keys"]

    def test_registers_org_dlv_unit_sn(self) -> None:
        """primary=주문상세 축, alt=배송단위 축(OrgDlvUnitSn)."""
        self.fn(
            "20260723B10697",
            {"OrgDlvUnitSn": "914395039", "OrdDtlSn": "1130501528"},
            "20260723B10697:1130501527",
        )
        assert self.alt_map == {
            "20260723B10697:1130501527": {"20260723B10697:914395039"}
        }

    def test_ignores_reissued_dlv_unit_sn(self) -> None:
        """클레임 응답의 DlvUnitSn 은 재발급 번호 — alt 로 쓰면 오매칭."""
        self.fn(
            "AA",
            {"DlvUnitSn": "999999", "OrdDtlSn": "111"},
            "AA:111",
        )
        assert self.alt_map == {}, "재발급 DlvUnitSn 이 alt 로 등록되면 안 됨"

    def test_skips_blank_and_placeholder(self) -> None:
        for _v in ("", "  ", "0", "null", "NONE"):
            self.fn("AA", {"OrgDlvUnitSn": _v}, "AA:111")
        assert self.alt_map == {}

    def test_skips_when_alt_equals_primary(self) -> None:
        """양축이 같은 값이면 alt 조회 자체가 불필요(자기 자신 매칭 방지)."""
        self.fn("AA", {"OrgDlvUnitSn": "111"}, "AA:111")
        assert self.alt_map == {}

    def test_skips_when_ord_no_or_primary_missing(self) -> None:
        self.fn("", {"OrgDlvUnitSn": "222"}, "AA:111")
        self.fn("AA", {"OrgDlvUnitSn": "222"}, "")
        assert self.alt_map == {}

    def test_accumulates_multiple_lines(self) -> None:
        """합배송 다중 라인 — primary 별로 각각 누적."""
        self.fn("AA", {"OrgDlvUnitSn": "901"}, "AA:1101")
        self.fn("AA", {"OrgDlvUnitSn": "902"}, "AA:1102")
        assert self.alt_map == {"AA:1101": {"AA:901"}, "AA:1102": {"AA:902"}}


class TestCallSites:
    """취소·반품 두 경로가 alt 키를 등록하는지(정적 계약)."""

    def setup_method(self) -> None:
        self.src = ORDER_PY.read_text(encoding="utf-8")

    def test_cancel_path_registers(self) -> None:
        idx = self.src.find("_lh_cncl = await lh_client.search_cancel_orders")
        assert idx != -1
        assert "_lh_reg_alt_keys(" in self.src[idx : idx + 1800], (
            "취소 경로 alt 키 등록 누락 — 유령 취소행 재발"
        )

    def test_return_path_registers(self) -> None:
        idx = self.src.find("_lh_ret = await lh_client.search_return_orders")
        assert idx != -1
        assert "_lh_reg_alt_keys(" in self.src[idx : idx + 3200], (
            "반품 경로 alt 키 등록 누락"
        )


class TestSecondLookupGuards:
    """2차 역조회 가드 — 오매칭 시 남의 주문에 취소를 덮어쓴다."""

    def setup_method(self) -> None:
        src = ORDER_PY.read_text(encoding="utf-8")
        idx = src.find("# 롯데홈쇼핑 이축 교차 매칭 (#688) — 2차 역조회.")
        assert idx != -1, "2차 역조회 블록 누락"
        self.block = src[idx : idx + 2600]

    def test_shared_alt_is_skipped(self) -> None:
        """같은 alt 를 primary 2개가 주장(합배송 배송단위 공유) → 매칭 포기."""
        assert "len(_ps) == 1" in self.block, "alt 중복 주장 시 포기 가드 누락"

    def test_tenant_and_channel_scoped(self) -> None:
        assert "tenant_id IS NOT DISTINCT FROM :tid" in self.block
        assert "channel_id IS NOT DISTINCT FROM :cid" in self.block

    def test_source_scoped_to_lottehome(self) -> None:
        assert "source = 'lottehome'" in self.block

    def test_does_not_overwrite_existing_match(self) -> None:
        """1차 매칭이 이미 성공한 primary 는 건드리지 않는다."""
        assert "if _pk in _existing_id_map:" in self.block

    def test_no_colon_cast_in_raw_sql(self) -> None:
        """SQLAlchemy text 의 `:name::type` 금지 패턴(silent fail 사고) 회귀 가드."""
        assert "::" not in self.block
