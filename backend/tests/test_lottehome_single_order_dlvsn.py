"""롯데홈쇼핑 단건 신규주문 송장전송 ord_dtl_sn 회귀 테스트.

배경:
  단건 신규주문 재전송 시 `[0005] 필수파라미터 오류 [ord_dtl_sn]` 로 롯데가 거부.
  원인: 신규주문 API(searchNewOrdLstOpenApi.lotte)는 registDeliver 가 요구하는 진짜
  출고단위번호(DlvUnitSn)를 안 주고 OrgOrdDtlSn(대체 큰 값)만 준다. 수집 코드가 이를
  그대로 ext_order_number 에 저장 → 전송 시 롯데가 유효한 ord_dtl_sn 아니라며 거부.

  합배송(ProdInfo list)은 search_deliver_list 로 만든 _lh_dlvsn_map 의 진짜 DlvUnitSn
  을 주입하는데, 단건(ProdInfo dict)은 그 보정을 안 거쳤던 것이 직접 원인.

fix:
  단건 신규주문 else 분기도 _lh_dlvsn_map[OrdNo] 의 DlvUnitSn 을 ProdInfo 에 주입.
  파서 기본 폴백 체인(OrdDtlSn→DlvUnitSn→OrgOrdDtlSn)에서 DlvUnitSn 이 OrgOrdDtlSn 보다
  앞서므로, 주입된 DlvUnitSn 이 ext_order_number 에 반영된다.

테스트:
  - 파서 불변식: ProdInfo 에 DlvUnitSn 있으면 OrgOrdDtlSn 대신 그 값으로 번호 조립.
  - 소스 가드: 단건 수집 분기가 DlvUnitSn 주입을 수행.
"""

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ORDER_PY = BACKEND_ROOT / "backend/api/v1/routers/samba/order.py"


def _load_parse_funcs() -> dict:
    """order.py 에서 _parse_lottehome_order(_multi) 만 격리 컴파일(순환 import 회피)."""
    src = ORDER_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    wanted = {"_parse_lottehome_order", "_parse_lottehome_order_multi"}
    funcs = [
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted
    ]
    mod = ast.Module(body=funcs, type_ignores=[])

    class _LoggerStub:
        def warning(self, *a, **k) -> None:
            pass

        def info(self, *a, **k) -> None:
            pass

    import re as _re

    ns: dict = {"logger": _LoggerStub(), "re": _re}
    exec(compile(mod, "<isolated>", "exec"), ns)
    return ns


class TestDlvUnitSnWinsOverOrgOrdDtlSn:
    """파서 불변식 — DlvUnitSn 주입이 OrgOrdDtlSn 대체값을 이긴다."""

    def setup_method(self) -> None:
        self.parse = _load_parse_funcs()["_parse_lottehome_order"]

    def test_dlvunitsn_used_when_present(self) -> None:
        """DlvUnitSn(진짜 출고단위번호) + OrgOrdDtlSn(대체값) 공존 → DlvUnitSn 채택."""
        item = {
            "OrdNo": "20260716H51347",
            "ProdInfo": {
                "DlvUnitSn": "3",  # 수집 fix 로 주입되는 진짜 값
                "OrgOrdDtlSn": "1129846184",  # 신규주문 API 대체값(잘못된 값)
                "ProdCode": "X",
                "ProdName": "t",
            },
        }
        r = self.parse(dict(item), "acc", "lbl", "pending", "주문접수")
        assert r["ext_order_number"] == "20260716H51347:3", (
            "DlvUnitSn 주입 시 ext_order_number 가 DlvUnitSn 을 써야 롯데 전송 성공"
        )
        assert r["order_number"] == "20260716H51347:3"

    def test_orgordtlsn_only_is_the_broken_case(self) -> None:
        """DlvUnitSn 없이 OrgOrdDtlSn 만(수집 보정 실패 시) → 잘못된 큰 값이 그대로.

        이 케이스가 바로 [0005] 필수파라미터 오류의 원인 — 수집 fix 가 없으면 여기로 떨어진다.
        """
        item = {
            "OrdNo": "20260716H51347",
            "ProdInfo": {
                "OrgOrdDtlSn": "1129846184",
                "ProdCode": "X",
                "ProdName": "t",
            },
        }
        r = self.parse(dict(item), "acc", "lbl", "pending", "주문접수")
        assert r["ext_order_number"] == "20260716H51347:1129846184"


class TestSingleOrderCollectionInjectsDlvUnitSn:
    """소스 가드 — 단건 신규주문 수집 분기가 DlvUnitSn 을 주입한다."""

    def setup_method(self) -> None:
        self.src = ORDER_PY.read_text(encoding="utf-8")

    def test_single_branch_injects_dlvsn(self) -> None:
        # 단건 else 분기에서 _lh_dlvsn_map 조회 후 ProdInfo 에 DlvUnitSn 주입
        assert "_dlvsn_list = _lh_dlvsn_map.get(_no_key, [])" in self.src, (
            "단건 신규주문 수집이 _lh_dlvsn_map 에서 DlvUnitSn 을 조회하지 않음"
        )
        assert '"DlvUnitSn": _real_dsn' in self.src, (
            "단건 신규주문 수집이 ProdInfo 에 진짜 DlvUnitSn 을 주입하지 않음"
        )

    def test_old_key_registered_for_cleanup(self) -> None:
        # 대체값으로 저장된 기존 레코드를 교체 삭제 대상으로 등록(중복 방지)
        assert (
            '_lh_replaced_old_keys.append(\n                                            f"{_no_key}:{_cur_dsn}"'
            in self.src
            or (
                "_lh_replaced_old_keys.append" in self.src
                and "{_no_key}:{_cur_dsn}" in self.src
            )
        ), "재수집 시 기존 잘못된 레코드가 삭제 대상으로 등록되지 않음"
