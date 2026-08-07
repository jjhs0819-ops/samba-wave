"""플레이오토 등록 후 이름캐시 무효화 회귀 테스트 (2026-08-06 실사고).

증상:
  데상트 997건 전송에서 같은 상품이 2~5중 등록(복제 189건). 복제본 생성 간격이
  6초로, 사전 중복조회(find_master_code_by_name)가 있는데도 전부 통과했다.

원인:
  이름→MasterCode 맵이 60초 캐시라, register 직후 초 단위 재시도의 사전조회가
  방금 EMP에 만들어진 상품을 못 본다(재시도 간격 6초 < TTL 60초). 응답 유실로
  실패 처리된 상품을 재시도할 때마다 새 업체상품코드로 복제본이 쌓였다.

수정:
  register_product 시도 직후(성공·타임아웃 불문, finally) 캐시를 무효화해
  다음 사전조회가 실목록을 다시 읽게 한다.
"""

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROXY_PY = BACKEND_ROOT / "backend/domain/samba/proxy/playauto.py"
PLUGIN_PY = BACKEND_ROOT / "backend/domain/samba/plugins/markets/playauto.py"


def _func_src(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.get_source_segment(text, n) or ""
    raise AssertionError(f"{name} 함수를 찾지 못함")


class TestRegisterCacheBust:
    def test_proxy_has_invalidator(self) -> None:
        src = _func_src(PROXY_PY, "invalidate_name_master_cache")
        assert "_NAME_MASTER_CACHE.pop" in src, "캐시 pop 누락"

    def test_plugin_busts_cache_in_finally_after_register(self) -> None:
        text = PLUGIN_PY.read_text(encoding="utf-8")
        tree = ast.parse(text)
        found = False
        for n in ast.walk(tree):
            if not isinstance(n, ast.Try):
                continue
            body_src = "".join(
                ast.get_source_segment(text, b) or "" for b in n.body
            )
            final_src = "".join(
                ast.get_source_segment(text, f) or "" for f in n.finalbody
            )
            if "register_product" in body_src and (
                "invalidate_name_master_cache" in final_src
            ):
                found = True
                break
        assert found, (
            "register_product 호출이 finally: invalidate_name_master_cache 로 "
            "감싸져 있지 않음 — 타임아웃 경로에서 캐시가 살아남아 재시도 복제 재발"
        )
