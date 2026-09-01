"""저재고 전송캡을 리셀 플랫폼에만 적용하는 회귀 테스트 (2026-08-14).

증상:
  롯데ON 에 올린 브룩스러닝 글리세린22 가 재고 있는 5개 사이즈(230/235/240/
  245/250) 중 240 하나만 노출됐다.

원인:
  저재고 오버셀 방지 캡(#703)이 마켓 구분 없이 전역 적용돼, stock<=2 인 옵션을
  전송값 0 으로 바꿔 마켓에서 미노출(dpYn=N) 처리했다. 위 상품은 240(5개)만
  임계값을 넘어 살아남았다.

수정:
  캡 적용 대상을 리셀 플랫폼(크림/포이즌)으로 한정. 크림/포이즌은 낙찰 후
  미발송이 페널티·정산차감으로 직결돼 마지막 1~2개를 내리는 편이 이득이지만,
  오픈마켓은 품절취소 리스크보다 노출 SKU 축소 손실이 크다.

캡 적용 지점이 두 곳(정상 send path / 실시간 재전송 path)이라 한쪽만 고치면
증상이 절반만 사라진다 — 두 곳 모두 가드되는지 함께 검증한다.
"""

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SERVICE_PY = BACKEND_ROOT / "backend/domain/samba/shipment/service.py"


class TestLowStockCapResellOnly:
    def setup_method(self) -> None:
        self.src = SERVICE_PY.read_text(encoding="utf-8")

    def test_cap_market_allowlist_is_resell_only(self) -> None:
        from backend.domain.samba.shipment.service import (
            _LOW_STOCK_SEND_CAP_MARKETS,
        )

        assert set(_LOW_STOCK_SEND_CAP_MARKETS) == {"kream", "poison"}, (
            "저재고 캡은 리셀 플랫폼(크림/포이즌)에만 적용해야 한다 — "
            f"현재: {sorted(_LOW_STOCK_SEND_CAP_MARKETS)}"
        )

    def test_open_markets_not_capped(self) -> None:
        from backend.domain.samba.shipment.service import (
            _LOW_STOCK_SEND_CAP_MARKETS,
        )

        # 오픈마켓은 실재고 그대로 나가야 한다(노출 SKU 축소 방지)
        for _mk in ("lotteon", "coupang", "smartstore", "11st", "gmarket", "auction"):
            assert _mk not in _LOW_STOCK_SEND_CAP_MARKETS, (
                f"{_mk} 는 오픈마켓인데 저재고 캡 대상에 포함됨 — "
                "재고 1~2개 옵션이 통째로 미노출된다"
            )

    def test_both_cap_sites_guarded_by_allowlist(self) -> None:
        """캡을 적용하는 두 경로 모두 마켓 허용목록 가드를 거쳐야 한다."""
        cap_sites = self.src.count("<= _LOW_STOCK_SEND_CAP_TH")
        guards = self.src.count("in _LOW_STOCK_SEND_CAP_MARKETS")
        assert cap_sites >= 2, (
            f"캡 적용 지점이 {cap_sites}곳 — 정상 send / 실시간 재전송 두 경로 예상"
        )
        assert guards == cap_sites, (
            f"캡 적용 {cap_sites}곳 중 마켓 가드는 {guards}곳뿐 — "
            "가드 없는 경로에서 오픈마켓 재고가 여전히 0 으로 캡된다"
        )
