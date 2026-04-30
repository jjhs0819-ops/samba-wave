"""롯데ON SPD 헤더 SOUT_ITM 자동 복구 회귀 테스트.

배경: 2026-04-30 LO2665417627(엠포리오 아르마니 양말) 사고. 옵션은 SALE/stkQty>0이지만
SPD 헤더가 SOUT/SOUT_ITM 잠겨있어 소비자 페이지에서 '품절된 상품입니다' 노출. 롯데ON은
옵션이 모두 stkQty=0이 되면 SPD를 자동으로 SOUT_ITM으로 escalate하지만 옵션을 다시 살려도
SPD는 자동 해제하지 않음. PR #98이 옵션은 살렸지만 SPD는 못 풀어서 잔존.

검증 항목 (codex 권고 6 케이스):
- t1: SPD SOUT/SOUT_ITM + item 이미 SALE+stkQty>0 → change_status(SALE)만 호출
- t2: SPD SOUT/SOUT_ITM + item SOUT/SOUT_STK+stkQty>0 → item 복구 후 SPD 복구 (양 phase)
- t3: SPD SOUT but rsn != SOUT_ITM → SPD phase skip (셀러 수동 SOUT 등 보존)
- t4: change_status outer code 실패 → warning만, 예외 X
- t5: get_product envelope 변형 (data.itmLst / spdLst[0].itmLst / spdInfo.itmLst)
- t6: SPD SALE + item SOUT/SOUT_STK → item phase만 실행 (PR #98 시나리오 회귀 방지)
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.plugins.markets.lotteon import LotteonPlugin


def _ok_response(items: list[dict] | None = None) -> dict:
    return {
        "returnCode": "0000",
        "message": "정상 처리되었습니다.",
        "data": items if items is not None else [],
    }


def _make_get_product_resp(spd_info: dict, envelope: str = "data") -> dict:
    """envelope 변형: data, spdLst, spdInfo."""
    if envelope == "data":
        return {"data": spd_info}
    if envelope == "spdLst":
        return {"data": {"spdLst": [spd_info]}}
    if envelope == "spdInfo":
        return {"data": {"spdInfo": spd_info}}
    raise ValueError(f"unknown envelope: {envelope}")


def _make_client(spd_info_sequence: list[dict]) -> MagicMock:
    """spd_info_sequence: get_product 호출 순서대로 반환할 spd_info 리스트.

    change_item_status / change_status는 기본 OK 응답.
    """
    client = MagicMock()
    client.get_product = AsyncMock(
        side_effect=[_make_get_product_resp(s) for s in spd_info_sequence]
    )
    client.change_item_status = AsyncMock(
        return_value=_ok_response([{"sitmNo": "X", "resultCode": "0000"}])
    )
    client.change_status = AsyncMock(
        return_value=_ok_response([{"spdNo": "X", "resultCode": "0000"}])
    )
    return client


# ──────────────────────────────────────────────────────────────────────
# Helper: _verify_change_status_response
# ──────────────────────────────────────────────────────────────────────
class TestVerifyChangeStatusResponse:
    def test_outer_ok_item_ok(self) -> None:
        ok, msg = LotteonPlugin._verify_change_status_response(
            {"returnCode": "0000", "data": [{"resultCode": "0000"}]}
        )
        assert ok and msg == ""

    def test_outer_fail(self) -> None:
        ok, msg = LotteonPlugin._verify_change_status_response(
            {"returnCode": "9999", "message": "fail", "data": []}
        )
        assert not ok
        assert "9999" in msg

    def test_item_fail(self) -> None:
        ok, msg = LotteonPlugin._verify_change_status_response(
            {
                "returnCode": "0000",
                "data": [
                    {
                        "spdNo": "LO1",
                        "resultCode": "8888",
                        "resultMessage": "이미 종료",
                    },
                ],
            }
        )
        assert not ok
        assert "8888" in msg

    def test_non_dict(self) -> None:
        ok, msg = LotteonPlugin._verify_change_status_response(None)
        assert not ok and "non-dict" in msg


# ──────────────────────────────────────────────────────────────────────
# Helper: _parse_lotteon_spd_info — t5 (envelope 변형)
# ──────────────────────────────────────────────────────────────────────
class TestParseLotteonSpdInfo:
    def test_data_itmlst(self) -> None:
        # data 직접 spd_info
        resp = {"data": {"spdNo": "LO1", "slStatCd": "SOUT", "itmLst": [{"a": 1}]}}
        info = LotteonPlugin._parse_lotteon_spd_info(resp)
        assert info["spdNo"] == "LO1"
        assert info["itmLst"] == [{"a": 1}]

    def test_spdlst_first(self) -> None:
        resp = {"data": {"spdLst": [{"spdNo": "LO1", "slStatCd": "SOUT"}]}}
        info = LotteonPlugin._parse_lotteon_spd_info(resp)
        assert info["spdNo"] == "LO1"

    def test_spdinfo(self) -> None:
        resp = {"data": {"spdInfo": {"spdNo": "LO1", "slStatCd": "SALE"}}}
        info = LotteonPlugin._parse_lotteon_spd_info(resp)
        assert info["slStatCd"] == "SALE"

    def test_empty(self) -> None:
        assert LotteonPlugin._parse_lotteon_spd_info({}) == {}
        assert LotteonPlugin._parse_lotteon_spd_info(None) == {}


# ──────────────────────────────────────────────────────────────────────
# t1: SPD SOUT/SOUT_ITM + item 이미 SALE+stkQty>0 → SPD phase만
# ──────────────────────────────────────────────────────────────────────
class TestT1ItemAlreadySaleSpdSout:
    async def test_only_change_status_called(self) -> None:
        plugin = LotteonPlugin()
        spd_info = {
            "spdNo": "LO_T1",
            "slStatCd": "SOUT",
            "slStatRsnCd": "SOUT_ITM",
            "itmLst": [
                {
                    "sitmNo": "S1",
                    "slStatCd": "SALE",
                    "slStatRsnCd": None,
                    "stkQty": 5,
                }
            ],
        }
        # item 변경이 없으므로 get_product는 1번만 (재조회 X)
        client = _make_client([spd_info])
        # itm_stk_lst는 update_stock으로 보낸 것 — stkQty>0이지만 item이 이미 SALE이라 복구 X
        await plugin._restore_sout_to_sale(
            client, "LO_T1", [{"sitmNo": "S1", "stkQty": 5}]
        )

        client.change_item_status.assert_not_called()
        client.change_status.assert_called_once()
        # 페이로드 검증 — 최소 페이로드 (trGrpCd/trNo는 client가 prepend)
        args, _ = client.change_status.call_args
        assert args[0] == [{"spdNo": "LO_T1", "slStatCd": "SALE"}]
        # get_product는 1번만 (item 변경 없으니 재조회 안 함)
        assert client.get_product.call_count == 1


# ──────────────────────────────────────────────────────────────────────
# t2: SPD SOUT/SOUT_ITM + item SOUT/SOUT_STK + stkQty>0 → 양 phase
# ──────────────────────────────────────────────────────────────────────
class TestT2BothPhases:
    async def test_item_then_spd(self) -> None:
        plugin = LotteonPlugin()
        # 1차 fetch: item SOUT_STK
        spd_before = {
            "spdNo": "LO_T2",
            "slStatCd": "SOUT",
            "slStatRsnCd": "SOUT_ITM",
            "itmLst": [
                {
                    "sitmNo": "S1",
                    "slStatCd": "SOUT",
                    "slStatRsnCd": "SOUT_STK",
                    "stkQty": 5,
                }
            ],
        }
        # 2차 fetch (item 복구 후): item SALE로 갱신, SPD는 아직 SOUT_ITM
        spd_after_items = {
            **spd_before,
            "itmLst": [
                {
                    "sitmNo": "S1",
                    "slStatCd": "SALE",
                    "slStatRsnCd": None,
                    "stkQty": 5,
                }
            ],
        }
        client = _make_client([spd_before, spd_after_items])
        await plugin._restore_sout_to_sale(
            client, "LO_T2", [{"sitmNo": "S1", "stkQty": 5}]
        )

        # item phase: change_item_status 호출됨
        client.change_item_status.assert_called_once()
        # SPD phase: change_status 호출됨
        client.change_status.assert_called_once()
        # 재조회: get_product 2번
        assert client.get_product.call_count == 2


# ──────────────────────────────────────────────────────────────────────
# t3: SPD SOUT but rsn != SOUT_ITM → SPD phase skip
# ──────────────────────────────────────────────────────────────────────
class TestT3SpdRsnNotSoutItm:
    async def test_skip_when_rsn_is_other(self) -> None:
        plugin = LotteonPlugin()
        spd_info = {
            "spdNo": "LO_T3",
            "slStatCd": "SOUT",
            "slStatRsnCd": "SOUT_AMT",  # 다른 사유 (셀러 수동)
            "itmLst": [
                {
                    "sitmNo": "S1",
                    "slStatCd": "SALE",
                    "slStatRsnCd": None,
                    "stkQty": 5,
                }
            ],
        }
        client = _make_client([spd_info])
        await plugin._restore_sout_to_sale(
            client, "LO_T3", [{"sitmNo": "S1", "stkQty": 5}]
        )

        client.change_status.assert_not_called()


# ──────────────────────────────────────────────────────────────────────
# t4: change_status outer code 실패 → warning, 예외 X
# ──────────────────────────────────────────────────────────────────────
class TestT4SpdRecoveryFailureSwallowed:
    async def test_failure_does_not_raise(self) -> None:
        plugin = LotteonPlugin()
        spd_info = {
            "spdNo": "LO_T4",
            "slStatCd": "SOUT",
            "slStatRsnCd": "SOUT_ITM",
            "itmLst": [
                {
                    "sitmNo": "S1",
                    "slStatCd": "SALE",
                    "slStatRsnCd": None,
                    "stkQty": 5,
                }
            ],
        }
        client = _make_client([spd_info])
        # change_status가 outer 실패 응답
        client.change_status = AsyncMock(
            return_value={"returnCode": "9999", "message": "권한 없음", "data": []}
        )
        # 예외가 일어나면 안 됨
        await plugin._restore_sout_to_sale(
            client, "LO_T4", [{"sitmNo": "S1", "stkQty": 5}]
        )
        client.change_status.assert_called_once()


# ──────────────────────────────────────────────────────────────────────
# t6: SPD SALE + item SOUT/SOUT_STK → item phase만 실행 (PR #98 회귀 방지)
# ──────────────────────────────────────────────────────────────────────
class TestT6Pr98RegressionItemOnly:
    async def test_item_phase_runs_spd_phase_skips(self) -> None:
        plugin = LotteonPlugin()
        spd_before = {
            "spdNo": "LO_T6",
            "slStatCd": "SALE",  # SPD는 정상
            "slStatRsnCd": None,
            "itmLst": [
                {
                    "sitmNo": "S1",
                    "slStatCd": "SOUT",
                    "slStatRsnCd": "SOUT_STK",
                    "stkQty": 5,
                }
            ],
        }
        spd_after_items = {
            **spd_before,
            "itmLst": [
                {
                    "sitmNo": "S1",
                    "slStatCd": "SALE",
                    "slStatRsnCd": None,
                    "stkQty": 5,
                }
            ],
        }
        client = _make_client([spd_before, spd_after_items])
        await plugin._restore_sout_to_sale(
            client, "LO_T6", [{"sitmNo": "S1", "stkQty": 5}]
        )

        client.change_item_status.assert_called_once()
        # SPD가 SALE이므로 SPD phase skip
        client.change_status.assert_not_called()


# ──────────────────────────────────────────────────────────────────────
# 추가: SPD phase 가드 — sellable item 없으면 skip
# ──────────────────────────────────────────────────────────────────────
class TestSpdPhaseRequiresSellableItem:
    async def test_skip_when_no_sellable_item(self) -> None:
        plugin = LotteonPlugin()
        # SPD SOUT_ITM이지만 모든 item이 stkQty=0 + SOUT
        spd_info = {
            "spdNo": "LO_T7",
            "slStatCd": "SOUT",
            "slStatRsnCd": "SOUT_ITM",
            "itmLst": [
                {
                    "sitmNo": "S1",
                    "slStatCd": "SOUT",
                    "slStatRsnCd": "SOUT_STK",
                    "stkQty": 0,
                }
            ],
        }
        client = _make_client([spd_info])
        # itm_stk_lst가 비어있어 item phase는 No-op
        await plugin._restore_sout_to_sale(client, "LO_T7", [])

        client.change_item_status.assert_not_called()
        # 실제 판매 가능 옵션 없으므로 SPD 복구 skip
        client.change_status.assert_not_called()
