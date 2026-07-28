"""플레이오토 품절(판매중지) 요청 형식 회귀 테스트 (2026-07-28 실측).

증상:
  플러그인 delete() → soldout_product() 경로가 처음부터 동작하지 않았다.
  로그는 늘 `상품 품절 응답: []` 였고 실패 사유조차 없었다.

원인:
  PATCH /prods/soldout 의 data 는 **배열**인데 CSV 문자열(",".join)을 보냈다.
  EMP 는 문자열 본문을 조용히 무시하고 빈 배열만 돌려준다.

실측 (동일 MasterCode, 같은 계정):
  {"data": "AM..."}                  → []                        (무시)
  {"data": ["AM..."]}                → [{code, status, message}]  (정상)
  {"data": [{"MasterCode": "AM..."}]} → 미등록 상품코드 오류

부수 버그:
  응답 키는 `message` 인데 호출부가 `msg` 만 읽어 실패 사유가 늘 빈 문자열이었다.
"""

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROXY_PY = BACKEND_ROOT / "backend/domain/samba/proxy/playauto.py"
PLUGIN_PY = BACKEND_ROOT / "backend/domain/samba/plugins/markets/playauto.py"


def _func_src(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.get_source_segment(path.read_text(encoding="utf-8"), n) or ""
    raise AssertionError(f"{name} 함수를 찾지 못함")


class TestSoldoutBody:
    def setup_method(self) -> None:
        self.src = _func_src(PROXY_PY, "soldout_product")

    def test_data_is_array_not_csv(self) -> None:
        assert '",".join(master_codes)' not in self.src, (
            "CSV 문자열 본문은 EMP 가 무시한다 — data 는 배열이어야 한다"
        )
        assert '"data": list(master_codes)' in self.src

    def test_empty_response_not_treated_as_success(self) -> None:
        """빈 응답은 '요청이 안 먹혔다'는 신호 — 성공 추론 금지."""
        assert "logger.error" in self.src, (
            "빈 응답을 에러로 남기지 않으면 또 조용히 실패한다"
        )


class TestDeleteCallSite:
    def setup_method(self) -> None:
        self.src = _func_src(PLUGIN_PY, "delete")

    def test_empty_response_is_failure(self) -> None:
        assert "if not results:" in self.src
        assert '"success": False' in self.src

    def test_reads_message_key(self) -> None:
        """EMP 응답 키는 message — msg 만 읽으면 실패 사유가 사라진다."""
        assert 'result.get("message")' in self.src, (
            "msg 만 읽으면 EMP 가 준 실패 사유가 빈 문자열로 버려진다"
        )
