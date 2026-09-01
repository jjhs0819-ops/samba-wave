"""쿠팡 전송 시 핫링크 차단 CDN 선미러 회귀 테스트 (2026-08-07 실사고).

증상:
  롯데온 소싱 상품 609건 승인반려 — 쿠팡 검수 화면에서 상세 이미지가 안 떠
  "상세페이지 미업로드" 판정.

원인:
  쿠팡 전송의 이미지 정규화가 mirror_oversized_to_r2(용량·픽셀 기준)만 호출.
  정상 용량의 핫링크 차단 CDN(contents.lotteon.com 등 _HOTLINK_BLOCKED_HOSTS)
  직링크는 그대로 통과 → 쿠팡 서버/검수 화면에서 fetch 실패.

수정:
  롯데홈 플러그인과 동일하게 mirror_with_persistence(차단 CDN → R2 + 영속 매핑)
  및 mirror_urls_in_html 을 oversized 정규화 앞단에 추가.
"""

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PY = BACKEND_ROOT / "backend/domain/samba/plugins/markets/coupang.py"


class TestMirrorBlockedCdn:
    def setup_method(self) -> None:
        self.src = PLUGIN_PY.read_text(encoding="utf-8")

    def test_images_premirrored_before_oversized(self) -> None:
        i_ext = self.src.find("await _img_svc.mirror_with_persistence")
        i_over = self.src.find("await _img_svc.mirror_oversized_to_r2")
        assert i_ext >= 0, "차단 CDN 선미러(mirror_with_persistence) 호출이 없음"
        assert i_over >= 0
        assert i_ext < i_over, (
            "선미러가 oversized 정규화보다 뒤에 있음 — 차단 CDN 직링크가 "
            "먼저 통과해 상세 미노출 반려 재발"
        )

    def test_detail_html_urls_mirrored(self) -> None:
        assert "mirror_urls_in_html" in self.src, (
            "detail_html 내 차단 CDN 치환(mirror_urls_in_html) 누락"
        )
