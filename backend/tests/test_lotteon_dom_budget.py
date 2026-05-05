"""롯데ON refresh wrapper budget + DOM 위임 동적 타임아웃 회귀 테스트.

배경: 2026-04-29 운영에서 [전체 처리 타임아웃: 60초] 다수 발생.
원인: wrapper(60s) == DOM 위임(60s) 충돌 → 안전망이 시작도 못 하고 잘림.
fix:
  1) refresher.py — LOTTEON/SSG wrapper 120초로 분기 (SITE_PRODUCT_TIMEOUT)
  2) lotteon.py  — DOM 위임 직전 잔여 예산 계산 → 동적 타임아웃,
                   예산 부족 시 DOM 스킵하여 pbf 값 유지
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestProductTimeoutHelper:
    """SITE_PRODUCT_TIMEOUT 분기 헬퍼 동작 검증."""

    def test_lotteon_returns_90(self) -> None:
        # 실측(2026-05-05): 확장앱 단건 22s + 큐 대기 60s + 마진 = 90s
        from backend.domain.samba.collector.refresher import get_product_timeout

        assert get_product_timeout("LOTTEON") == 90

    def test_ssg_returns_90(self) -> None:
        # 실측(2026-05-05): 확장앱 단건 17s/p90=21s + 큐 대기 60s + 마진 = 90s
        from backend.domain.samba.collector.refresher import get_product_timeout

        assert get_product_timeout("SSG") == 90

    def test_musinsa_returns_default_60(self) -> None:
        # 비-확장앱 마켓은 기본 60s
        from backend.domain.samba.collector.refresher import get_product_timeout

        assert get_product_timeout("MUSINSA") == 60

    def test_unknown_site_falls_back_to_default(self) -> None:
        # 미정의 마켓도 기본값 폴백
        from backend.domain.samba.collector.refresher import get_product_timeout

        assert get_product_timeout("UNKNOWN_SITE") == 60

    def test_default_constant_is_60(self) -> None:
        # 기본값 자체 검증 — 다른 마켓 wrapper 한계 그대로
        from backend.domain.samba.collector.refresher import PRODUCT_TIMEOUT_DEFAULT

        assert PRODUCT_TIMEOUT_DEFAULT == 60


class TestDomBudgetCalc:
    """DOM 잔여 예산 → 동적 타임아웃 산식 검증.

    공식: ``_dom_timeout = min(60, max(0, int(wrapper - elapsed - safety)))``
    - wrapper=120 (LOTTEON)
    - safety=5 (qapi 보정 + 후처리 + IO 진동 여유)
    - 상한 60초 (DOM 위임 본래 안전망 상한 — 큐 적체 흡수 의도)
    """

    @staticmethod
    def _calc(elapsed: float, wrapper: int = 120, safety: int = 5) -> int:
        remaining = wrapper - elapsed - safety
        return min(60, max(0, int(remaining)))

    def test_cache_hit_fast_keeps_full_60(self) -> None:
        # 캐시 적중 빠른 경로(3초): DOM 60초 안전망 그대로
        assert self._calc(elapsed=3) == 60

    def test_cache_hit_max_keeps_full_60(self) -> None:
        # 캐시 적중 최악(20초 = pbf 빠른경로 timeout): DOM 60초 안전망 그대로
        assert self._calc(elapsed=20) == 60

    def test_cache_miss_uses_remaining_only(self) -> None:
        # 캐시 미적중 worst(70초 = HTML45 + pbf보강15 + 여유10): 잔여 45초만 대기
        assert self._calc(elapsed=70) == 45

    def test_partial_cache_miss_uses_remaining(self) -> None:
        # 캐시 미적중 정상(60초 = HTML45 + pbf보강15): 잔여 55초 대기
        assert self._calc(elapsed=60) == 55

    def test_budget_almost_exhausted_skips(self) -> None:
        # 예산 거의 소진(115초): 잔여 0초 → DOM 스킵
        assert self._calc(elapsed=115) == 0

    def test_budget_overrun_negative_remaining_skips(self) -> None:
        # 예산 초과(125초): 음수 잔여 → DOM 스킵
        assert self._calc(elapsed=125) == 0

    def test_default_market_budget_consistent(self) -> None:
        # 기본 마켓(60s wrapper) 가정 시에도 산식 일관성 (안전 폴백)
        assert self._calc(elapsed=10, wrapper=60) == 45
        assert self._calc(elapsed=55, wrapper=60) == 0


class TestSitePtoMapping:
    """SITE_PRODUCT_TIMEOUT 정의가 실제 의도와 일치하는지 직접 확인."""

    def test_lotteon_in_map(self) -> None:
        from backend.domain.samba.collector.refresher import SITE_PRODUCT_TIMEOUT

        assert SITE_PRODUCT_TIMEOUT["LOTTEON"] == 90

    def test_ssg_in_map(self) -> None:
        from backend.domain.samba.collector.refresher import SITE_PRODUCT_TIMEOUT

        assert SITE_PRODUCT_TIMEOUT["SSG"] == 90

    def test_abcmart_in_map(self) -> None:
        # 실측(2026-05-05) 기반: 확장앱 단건 13-26s + 큐 대기 60s + 마진 = 90s
        from backend.domain.samba.collector.refresher import SITE_PRODUCT_TIMEOUT

        assert SITE_PRODUCT_TIMEOUT["ABCmart"] == 90
        assert SITE_PRODUCT_TIMEOUT["GrandStage"] == 90

    def test_musinsa_not_overridden(self) -> None:
        # 순수 백엔드 처리(확장앱 무관) 마켓이 잘못 추가되지 않았는지 확인
        from backend.domain.samba.collector.refresher import SITE_PRODUCT_TIMEOUT

        assert "MUSINSA" not in SITE_PRODUCT_TIMEOUT
        assert "KREAM" not in SITE_PRODUCT_TIMEOUT
