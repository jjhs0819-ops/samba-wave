"""쿠팡 contents 타입 짝 검증 회귀 테스트 (2026-08-07 실사고).

증상:
  재전송 전량 승인반려 — "[S, L, M]: 상세컨텐츠의 세부타입 설정이 잘 못
  되었습니다. 컨텐츠타입에 맞는 세부타입을 입력해 주세요."
  (종전 등록분은 통과했던 규칙 → 쿠팡 측 검증 강화)

원인:
  contents 를 contentsType=HTML 단일 블록으로 보내면서 contentDetails 에
  TEXT/IMAGE 조각을 혼합 — 쿠팡이 contentsType 과 detailType 의 짝을
  강제하면서 전건 거절.

수정:
  _build_contents_blocks — detailType 연속 구간별로 TEXT ↔ TEXT,
  IMAGE ↔ IMAGE_NO_SPACE 블록으로 분리.
"""

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

# proxy.coupang import 시 BackendSettings(DB env)가 필요 — 테스트는 DB 무관
for _k, _v in {
    "WRITE_DB_USER": "x",
    "WRITE_DB_PASSWORD": "x",
    "WRITE_DB_HOST": "x",
    "WRITE_DB_PORT": "5432",
    "WRITE_DB_NAME": "x",
    "READ_DB_USER": "x",
    "READ_DB_PASSWORD": "x",
    "READ_DB_HOST": "x",
    "READ_DB_PORT": "5432",
    "READ_DB_NAME": "x",
    "JWT_SECRET_KEY": "x",
}.items():
    os.environ.setdefault(_k, _v)

from backend.domain.samba.proxy.coupang import _build_contents_blocks  # noqa: E402


class TestContentsBlocks:
    def test_mixed_details_split_by_type(self) -> None:
        details = [
            {"content": "<p>intro</p>", "detailType": "TEXT"},
            {"content": "https://x/1.jpg", "detailType": "IMAGE"},
            {"content": "https://x/2.jpg", "detailType": "IMAGE"},
            {"content": "<p>outro</p>", "detailType": "TEXT"},
        ]
        blocks = _build_contents_blocks(details)
        assert [b["contentsType"] for b in blocks] == [
            "TEXT",
            "IMAGE_NO_SPACE",
            "TEXT",
        ]
        for b in blocks:
            for d in b["contentDetails"]:
                if b["contentsType"] == "TEXT":
                    assert d["detailType"] == "TEXT"
                else:
                    assert d["detailType"] == "IMAGE"

    def test_no_html_contents_type(self) -> None:
        details = [{"content": "https://x/1.jpg", "detailType": "IMAGE"}]
        blocks = _build_contents_blocks(details)
        assert all(b["contentsType"] != "HTML" for b in blocks)

    def test_empty_details_fallback(self) -> None:
        blocks = _build_contents_blocks([])
        assert blocks[0]["contentsType"] == "TEXT"
        assert blocks[0]["contentDetails"][0]["detailType"] == "TEXT"

    def test_transform_no_longer_uses_html_block(self) -> None:
        src = (BACKEND_ROOT / "backend/domain/samba/proxy/coupang.py").read_text(
            encoding="utf-8"
        )
        assert '"contentsType": "HTML"' not in src.replace("contentsType=HTML", ""), (
            "HTML 단일 블록 조립이 부활함 — 타입 짝 반려 재발"
        )
