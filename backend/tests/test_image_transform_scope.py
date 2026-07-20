"""AI 이미지 변환 scope 게이팅 회귀 테스트 (issue #665).

배경:
  AI 이미지 변환의 범위 체크박스(대표/추가/상세)를 선택해도 Gemini 기반 3개 모드
  (연출컷 scene · 모델착용 model · 모델→상품 model_to_product)가 이를 무시하고
  선택하지 않은 이미지까지 유료(Gemini, 장당 ~55원) 변환하던 문제.
  특히 연출컷은 추가이미지 없으면 체크 안 한 상세 전체를 변환하는 fallback이 있었음.

fix:
  세 모드 모두 scope.get("thumbnail"/"additional"/"detail")로 변환 범위를 게이팅.
  scene의 "추가 없으면 상세" fallback 제거(상세는 detail 체크 시에만).

테스트:
  transform_products() 소스에서 각 모드 분기가 scope 게이팅을 수행하고,
  과금 유발 fallback이 제거됐는지 소스 가드로 검증(실제 실행은 DB/Gemini 의존이라 격리 곤란).
"""

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SERVICE_PY = BACKEND_ROOT / "backend/domain/samba/image/service.py"


def _transform_products_src() -> str:
    """service.py에서 transform_products 메서드 본문만 추출."""
    src = SERVICE_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
            and node.name == "transform_products"
        ):
            return ast.get_source_segment(src, node) or ""
    raise AssertionError("transform_products 메서드를 찾지 못함")


class TestScopeGating:
    def setup_method(self) -> None:
        self.body = _transform_products_src()

    def test_scene_reads_scope(self) -> None:
        """연출컷 모드가 scope 대표/추가/상세를 게이팅."""
        i = self.body.index('elif mode == "scene"')
        j = self.body.index('elif mode == "model_to_product"')
        scene = self.body[i:j]
        assert 'use_thumbnail = scope.get("thumbnail"' in scene
        assert 'use_additional = scope.get("additional"' in scene
        assert 'use_detail = scope.get("detail"' in scene
        assert "if use_thumbnail:" in scene
        assert "if use_additional and" in scene
        assert "if use_detail and" in scene

    def test_scene_no_detail_fallback(self) -> None:
        """연출컷에서 '추가 없으면 상세 전체 변환' fallback 제거 확인(과금 원인)."""
        i = self.body.index('elif mode == "scene"')
        j = self.body.index('elif mode == "model_to_product"')
        scene = self.body[i:j]
        assert "elif product.detail_images:" not in scene, (
            "추가이미지 없을 때 상세 전체를 유료 변환하는 fallback이 아직 존재"
        )

    def test_model_reads_scope(self) -> None:
        """모델착용 모드가 대표/추가를 게이팅하고, 전부 실패 시 images 미변경."""
        i = self.body.index('if mode == "model" and product_images:')
        j = self.body.index('elif mode == "scene"')
        model = self.body[i:j]
        assert 'use_thumbnail = scope.get("thumbnail"' in model
        assert 'use_additional = scope.get("additional"' in model
        assert "if use_thumbnail:" in model
        assert "if use_additional:" in model
        # 전부 실패 시 원본 유실 방지 가드
        assert 'if product_result["transformed"] > 0:' in model

    def test_model_to_product_reads_scope(self) -> None:
        """모델→상품 모드가 idx별(대표/추가) + 상세 scope를 게이팅."""
        i = self.body.index('elif mode == "model_to_product"')
        j = self.body.index("# ── 배경제거 등 기본 모드")
        m2p = self.body[i:j]
        assert 'use_thumbnail = scope.get("thumbnail"' in m2p
        assert 'use_additional = scope.get("additional"' in m2p
        assert 'use_detail = scope.get("detail"' in m2p
        assert "if idx == 0 and not use_thumbnail:" in m2p
        assert "if idx >= 1 and not use_additional:" in m2p
        assert "if use_detail and product.detail_images:" in m2p
