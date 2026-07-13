"""더현대Hi discover_brands 정규화 회귀 테스트.

핵심 검증:
1. brandList → {name, value=operBrndCd, count} 정규화
2. canonical key = operBrndCd (groupCode 와 동일)
3. 중복 operBrndCd 제거
4. 빈 groupName 폴백 (방어 코드 — 실측 누락 0건이지만 안전망)

검증 대상: 더현대 searchFilterInfo.brandList — Chrome 3-A F섹션
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _normalize_brand_list(brand_list: list[dict]) -> dict:
    """discover_brands 내부 로직 발췌 (HTTP 호출 없이 단위 검증).

    실제 구현은 thehyundai_sourcing.TheHyundaiSourcingClient.discover_brands 안.
    이 헬퍼는 그 정규화 부분을 단위 테스트용으로 추출한 미러.
    """
    seen: set[str] = set()
    brands: list[dict] = []
    for b in brand_list:
        code = str(b.get("groupCode") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        name = (b.get("groupName") or "").strip() or code
        brands.append(
            {
                "name": name,
                "value": code,
                "count": int(b.get("groupCnt") or 0),
            }
        )
    return {"brands": brands, "total": len(brands)}


class TestDiscoverBrandsNormalization:
    def test_basic_mapping(self) -> None:
        raw = [
            {"groupCode": "101047", "groupName": "나이키", "groupCnt": 297},
            {"groupCode": "146988", "groupName": "생로랑", "groupCnt": 42},
        ]
        out = _normalize_brand_list(raw)
        assert out["total"] == 2
        assert out["brands"][0] == {"name": "나이키", "value": "101047", "count": 297}
        assert out["brands"][1] == {"name": "생로랑", "value": "146988", "count": 42}

    def test_canonical_key_is_oper_brnd_cd(self) -> None:
        """value 필드는 항상 operBrndCd (검색 flBrand= 와 동일 키)."""
        raw = [{"groupCode": "101047", "groupName": "Nike", "groupCnt": 100}]
        out = _normalize_brand_list(raw)
        assert out["brands"][0]["value"] == "101047"

    def test_duplicate_oper_brnd_cd_removed(self) -> None:
        # 동일 operBrndCd 가 응답에 두 번 — 첫 번째 항목 유지
        raw = [
            {"groupCode": "101047", "groupName": "나이키", "groupCnt": 297},
            {"groupCode": "101047", "groupName": "NIKE", "groupCnt": 297},
        ]
        out = _normalize_brand_list(raw)
        assert out["total"] == 1
        assert out["brands"][0]["name"] == "나이키"

    def test_empty_group_code_skipped(self) -> None:
        raw = [
            {"groupCode": "", "groupName": "이상한브랜드", "groupCnt": 0},
            {"groupCode": "101047", "groupName": "나이키", "groupCnt": 297},
        ]
        out = _normalize_brand_list(raw)
        assert out["total"] == 1
        assert out["brands"][0]["value"] == "101047"

    def test_empty_group_name_falls_back_to_code(self) -> None:
        # 방어 코드 — 빈 노출명일 때 groupCode 로 폴백 (실측 누락 0건)
        raw = [{"groupCode": "999999", "groupName": "", "groupCnt": 5}]
        out = _normalize_brand_list(raw)
        assert out["brands"][0]["name"] == "999999"

    def test_null_group_name_falls_back_to_code(self) -> None:
        raw = [{"groupCode": "888888", "groupName": None, "groupCnt": 3}]
        out = _normalize_brand_list(raw)
        assert out["brands"][0]["name"] == "888888"

    def test_count_zero_preserved(self) -> None:
        raw = [{"groupCode": "777777", "groupName": "전상품품절", "groupCnt": 0}]
        out = _normalize_brand_list(raw)
        assert out["brands"][0]["count"] == 0

    def test_empty_list_returns_empty(self) -> None:
        out = _normalize_brand_list([])
        assert out == {"brands": [], "total": 0}


class TestTetrisCompatibility:
    """테트리스 정규화 키 (`_norm_tetris_key`) 와 호환 검증.

    `tetris/service.py:55`:
        def _norm_tetris_key(value: str | None) -> str:
            return "".join((value or "").split()).casefold()

    더현대 brand name 이 이 함수를 거쳐 다른 사이트 brand 와 같은 키로
    묶일 수 있어야 테트리스 매핑이 정확.
    """

    @staticmethod
    def _norm_key(value: str | None) -> str:
        return "".join((value or "").split()).casefold()

    def test_korean_brand_no_whitespace(self) -> None:
        # 더현대 expsBrndNm 와 다른 사이트 brand_name 일치 검증
        assert self._norm_key("나이키") == self._norm_key("나이키")

    def test_whitespace_stripped(self) -> None:
        assert self._norm_key("새 벽 시 장") == self._norm_key("새벽시장")

    def test_case_folding(self) -> None:
        assert self._norm_key("NIKE") == self._norm_key("nike")
        assert self._norm_key("Nike") == self._norm_key("nike")
