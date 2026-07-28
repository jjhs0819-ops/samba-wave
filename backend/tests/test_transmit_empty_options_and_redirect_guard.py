"""옵션 0건 전송 보류(#690) + 플레이오토 쓰기 리다이렉트 차단(#691) 회귀 테스트.

#690 보류 가드의 함정:
  skip 분기가 즉시 return 하므로 이번 회차 갱신 결과(last_refreshed_at/options)를
  저장하는 통합 지점(update_data)에 도달하지 못한다. 저장 없이 빠지면
  last_refreshed_at 이 영원히 NULL → 다음 회차도 같은 조건으로 보류 → 무한 루프.
  미등록 상품은 오토튠 갱신 대상이 아니라(registered_accounts 필터) 이 경로 말고는
  채워줄 곳이 없어, 진짜 단일상품(옵션 0건 확정)이 영구 미등록으로 남는다.

#691:
  httpx 는 307/308 에서 본문을 그대로 재전송한다 → EMP 등록이 요청 1회당 2~3건 복제.
  쓰기 요청만 follow_redirects=False 로 끊고, 3xx 응답은 명시적 실패로 처리한다
  (추종을 껐으므로 리다이렉트 본문을 JSON 파싱하다 새는 것도 함께 차단).
"""

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SHIPMENT_PY = BACKEND_ROOT / "backend/domain/samba/shipment/service.py"
PLAYAUTO_PY = BACKEND_ROOT / "backend/domain/samba/proxy/playauto.py"


class TestEmptyOptionsGuard:
    def setup_method(self) -> None:
        src = SHIPMENT_PY.read_text(encoding="utf-8")
        idx = src.find("# 옵션 0건 + 미갱신 방어")
        assert idx != -1, "옵션 0건 보류 가드 누락"
        self.block = src[idx : idx + 2400]

    def test_guard_conditions(self) -> None:
        """옵션 0건 + 미갱신 + price/stock 전용 아님 → 보류."""
        assert "product_row.last_refreshed_at is None" in self.block
        assert "not _price_stock_only" in self.block

    def test_uses_pending_refresh_options(self) -> None:
        """전송 직전 실시간 재조회가 옵션을 회복했으면 통과해야 한다."""
        assert '(pending_refresh_updates or {}).get("options")' in self.block, (
            "DB 스냅샷만 보면 방금 회복된 옵션을 무시하고 불필요하게 보류한다"
        )

    def test_persists_refresh_before_skip(self) -> None:
        """보류 전에 갱신 결과를 저장해야 무한 보류를 피한다 (핵심 회귀)."""
        persist = self.block.find("product_repo.update_async(")
        ret = self.block.find("return shipment")
        assert persist != -1, (
            "보류 시 last_refreshed_at 을 저장하지 않으면 다음 회차도 같은 조건으로 "
            "보류돼 진짜 단일상품이 영구 미등록으로 남는다"
        )
        assert persist < ret, "저장이 return 뒤에 있으면 실행되지 않는다"

    def test_skip_recorded_as_shipment(self) -> None:
        assert 'status="skipped"' in self.block


class TestPlayautoRedirectGuard:
    def setup_method(self) -> None:
        self.src = PLAYAUTO_PY.read_text(encoding="utf-8")

    def test_write_requests_disable_follow(self) -> None:
        assert 'kwargs["follow_redirects"] = False' in self.src, (
            "쓰기 요청 리다이렉트 추종을 끄지 않으면 307/308 본문 재전송으로 중복등록"
        )

    def test_get_still_follows(self) -> None:
        """GET 은 기존대로 추종 — 조회 흐름 회귀 금지."""
        idx = self.src.find('kwargs["follow_redirects"] = False')
        head = self.src[max(0, idx - 300) : idx]
        assert 'method.upper() != "GET"' in head, "GET 까지 추종을 끄면 조회가 깨진다"

    def test_redirect_raises_for_writes(self) -> None:
        idx = self.src.find("리다이렉트 차단 감지")
        assert idx != -1, "리다이렉트 응답 처리 블록 누락"
        block = self.src[idx : idx + 1400]
        for code in ("301", "302", "307", "308"):
            assert code in block, (
                f"{code} 미처리 — 리다이렉트 본문이 JSON 파싱으로 샌다"
            )
        assert "raise PlayAutoApiError" in block
        assert "location" in block, "location 을 안 남기면 진범(EMP/프록시)을 못 가린다"

    def test_client_default_unchanged(self) -> None:
        """클라이언트 기본값은 True 유지 — 요청별 override 로만 끈다."""
        assert "follow_redirects=True," in self.src
