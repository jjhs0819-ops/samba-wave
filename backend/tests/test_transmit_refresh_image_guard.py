"""전송 중 소싱처 재수집이 AI 변환 이미지를 원본으로 되돌리지 않는지 검증 (2026-08-14).

배경:
  AI 이미지 변환은 samba_collected_product.images 를 변환본 URL 로 **in-place**
  덮어쓴다(원본 백업 컬럼이 없다). 그런데 전송 중 품절 재수집(refresh) 경로는
  update_items 에 "image" 가 있으면 소싱처 원본으로 다시 덮어쓰고 있었고,
  ai_image_transformed / __img_edited__ 검사가 없었다.

위험:
  데상트·엠엘비(지재권 신고) / 마뗑킴(마크비전 신고)은 이미지 변환이 판매 전제다.
  변환본이 원본으로 되돌아가면 그 원본이 쿠팡·스마트스토어 등으로 그대로 나가
  지재권 사고로 직결된다.

참고:
  같은 성격의 가드가 collector_refresh.py 갱신 경로에는 이미 있었다 —
  전송 경로에만 빠져 있어 보호가 비대칭이었다.
"""

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SERVICE_PY = BACKEND_ROOT / "backend/domain/samba/shipment/service.py"


class TestTransmitRefreshImageGuard:
    def setup_method(self) -> None:
        self.src = SERVICE_PY.read_text(encoding="utf-8")

    def test_image_refresh_guarded_by_transform_flag(self) -> None:
        """이미지 갱신 판단에 변환/편집 여부가 반영돼야 한다."""
        assert "_img_locked" in self.src, (
            "전송 중 이미지 갱신에 AI변환 보호 가드가 없음 — 변환본이 원본으로 되돌아간다"
        )
        assert "ai_image_transformed" in self.src, (
            "ai_image_transformed 플래그를 보지 않음"
        )

    def test_guard_checks_edit_markers(self) -> None:
        """플래그 외에 편집 마커 태그도 함께 봐야 한다(플래그 도입 이전 상품 대응)."""
        for marker in ("__ai_image__", "__img_edited__", "__img_filtered__"):
            assert marker in self.src, f"편집 마커 {marker} 미검사"

    def test_guard_applied_before_images_assignment(self) -> None:
        """가드가 images/detail_images 대입보다 앞에 있어야 실제로 막힌다."""
        i_guard = self.src.find("_img_locked")
        i_assign = self.src.find(
            'refresh_updates["images"] = refresh_result.new_images'
        )
        assert i_guard >= 0 and i_assign >= 0
        assert i_guard < i_assign, "가드가 images 대입보다 뒤에 있어 실효가 없음"

    def test_update_image_depends_on_guard(self) -> None:
        """_update_image 계산에 가드가 실제로 결합돼 있어야 한다."""
        i = self.src.find("_update_image = (")
        assert i >= 0, "_update_image 계산부를 찾지 못함"
        block = self.src[i : i + 200]
        assert "not _img_locked" in block, (
            f"_update_image 가 가드를 반영하지 않음: {block[:120]!r}"
        )
