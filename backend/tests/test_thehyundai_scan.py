"""더현대Hi 카테고리 트리 빌드 회귀 테스트.

핵심 검증:
1. 4단계(cateL/M/S/D) → 평탄화 path 정확성
2. highGroupCode 부모 추적
3. cycle guard (혹시 모를 self-reference)
4. SKIP 키워드 — 여행 / 컬처/서비스 > E쿠폰 / 컬처/서비스 > 서비스 / 컬처/서비스 > 컬처
5. categoryCode 필드 — brands.py 필터에서 사용
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.proxy.thehyundai_sourcing import TheHyundaiSourcingClient


# ──────────────────────────────────────────────────────────────
# fixture — Chrome 2차 E섹션 raw 발췌
# ──────────────────────────────────────────────────────────────

FILTER_INFO_FIXTURE = {
    "cateLList": {
        "totalSize": 4,
        "groupInfoList": [
            {"groupCode": "400003", "groupName": "패션", "groupCnt": 438445},
            {"groupCode": "400004", "groupName": "레저/스포츠", "groupCnt": 98576},
            {"groupCode": "400007", "groupName": "컬처/서비스", "groupCnt": 2858},
            {"groupCode": "400008", "groupName": "여행", "groupCnt": 72},
        ],
    },
    "cateMList": {
        "totalSize": 5,
        "groupInfoList": [
            {"groupCode": "400029", "groupName": "상의", "groupCnt": 117103,
             "highGroupCode": "400003"},
            {"groupCode": "400035", "groupName": "슈즈", "groupCnt": 39507,
             "highGroupCode": "400003"},
            {"groupCode": "400064", "groupName": "국내여행", "groupCnt": 35,
             "highGroupCode": "400008"},
            {"groupCode": "400067", "groupName": "컬처", "groupCnt": 1100,
             "highGroupCode": "400007"},
            {"groupCode": "400071", "groupName": "E쿠폰", "groupCnt": 87,
             "highGroupCode": "400007"},
        ],
    },
    "cateSList": {
        "totalSize": 1,
        "groupInfoList": [
            {"groupCode": "400251", "groupName": "스니커즈", "groupCnt": 12357,
             "highGroupCode": "400035"},
        ],
    },
    "cateDList": {
        "totalSize": 0,
        "groupInfoList": [],
    },
}


class TestBuildCategoryTree:
    def test_returns_expected_shape(self) -> None:
        out = TheHyundaiSourcingClient._build_category_tree(FILTER_INFO_FIXTURE)
        assert "categories" in out
        assert "total" in out
        assert "groupCount" in out
        assert isinstance(out["categories"], list)

    def test_top_level_categories_have_no_separator(self) -> None:
        out = TheHyundaiSourcingClient._build_category_tree(FILTER_INFO_FIXTURE)
        paths = {c["path"]: c for c in out["categories"]}
        assert "패션" in paths
        assert paths["패션"]["id"] == "400003"
        assert paths["패션"]["count"] == 438445

    def test_nested_path_uses_arrow_separator(self) -> None:
        out = TheHyundaiSourcingClient._build_category_tree(FILTER_INFO_FIXTURE)
        paths = {c["path"]: c for c in out["categories"]}
        # cateM 노드 → "대 > 중" 형식
        assert "패션 > 상의" in paths
        assert "패션 > 슈즈" in paths

    def test_deep_path_l_m_s_levels(self) -> None:
        out = TheHyundaiSourcingClient._build_category_tree(FILTER_INFO_FIXTURE)
        paths = {c["path"]: c for c in out["categories"]}
        assert "패션 > 슈즈 > 스니커즈" in paths
        assert paths["패션 > 슈즈 > 스니커즈"]["id"] == "400251"
        assert paths["패션 > 슈즈 > 스니커즈"]["count"] == 12357

    def test_skip_travel_top_category(self) -> None:
        out = TheHyundaiSourcingClient._build_category_tree(FILTER_INFO_FIXTURE)
        paths = {c["path"] for c in out["categories"]}
        # 여행 top + 그 자식 (국내여행) 모두 제외
        assert "여행" not in paths
        assert "여행 > 국내여행" not in paths

    def test_skip_e_coupon_sub_path(self) -> None:
        out = TheHyundaiSourcingClient._build_category_tree(FILTER_INFO_FIXTURE)
        paths = {c["path"] for c in out["categories"]}
        # 컬처/서비스 > E쿠폰 제외
        assert "컬처/서비스 > E쿠폰" not in paths

    def test_total_sums_top_level_counts(self) -> None:
        out = TheHyundaiSourcingClient._build_category_tree(FILTER_INFO_FIXTURE)
        # total = 대분류 합 (parent 없는 노드)
        # 438,445 + 98,576 + 2,858 + 72 = 539,951
        assert out["total"] == 539951

    def test_category_code_field_present(self) -> None:
        # brands.py:225 가 c.get("categoryCode") 로 필터링 → 필드 필수
        out = TheHyundaiSourcingClient._build_category_tree(FILTER_INFO_FIXTURE)
        for c in out["categories"]:
            assert c.get("categoryCode") == c.get("id")

    def test_group_count_excludes_skipped(self) -> None:
        out = TheHyundaiSourcingClient._build_category_tree(FILTER_INFO_FIXTURE)
        # fixture nodes 수: cateL(4) + cateM(5) + cateS(1) + cateD(0) = 10
        # SKIP: 여행(1) + 여행>국내여행(1) + 컬처/서비스>E쿠폰(1) + 컬처/서비스>컬처(1) = 4
        # 단, "컬처/서비스" top 자체는 SKIP prefix 직접 매칭 없음 → 통과
        # 결과: 10 - 4 = 6
        assert out["groupCount"] == 6
        paths = {c["path"] for c in out["categories"]}
        # 명시 검증 — 무엇이 통과/제외되는지
        assert paths == {
            "패션",
            "레저/스포츠",
            "컬처/서비스",  # top 통과
            "패션 > 상의",
            "패션 > 슈즈",
            "패션 > 슈즈 > 스니커즈",
        }

    def test_cycle_guard_handles_self_reference(self) -> None:
        # 사이트 응답이 self-referencing 노드를 보낼 가능성 (현실엔 없겠지만 방어)
        bad_fixture = {
            "cateLList": {
                "groupInfoList": [
                    {"groupCode": "X", "groupName": "Loop", "groupCnt": 0,
                     "highGroupCode": "X"},  # self-reference
                ],
            },
            "cateMList": {"groupInfoList": []},
            "cateSList": {"groupInfoList": []},
            "cateDList": {"groupInfoList": []},
        }
        # 무한 루프 안 빠지고 정상 종료
        out = TheHyundaiSourcingClient._build_category_tree(bad_fixture)
        assert len(out["categories"]) == 1
        # cycle guard 작동 — path는 한 번만 "Loop"
        assert out["categories"][0]["path"] == "Loop"

    def test_empty_filter_info(self) -> None:
        empty = {
            "cateLList": {"groupInfoList": []},
            "cateMList": {"groupInfoList": []},
            "cateSList": {"groupInfoList": []},
            "cateDList": {"groupInfoList": []},
        }
        out = TheHyundaiSourcingClient._build_category_tree(empty)
        assert out["categories"] == []
        assert out["total"] == 0
        assert out["groupCount"] == 0

    def test_missing_high_group_code_top_level(self) -> None:
        # cateL 노드는 highGroupCode 없거나 빈 문자열 — parent=None 처리
        fixture = {
            "cateLList": {
                "groupInfoList": [
                    {"groupCode": "A", "groupName": "TopA", "groupCnt": 10},
                    {"groupCode": "B", "groupName": "TopB", "groupCnt": 5,
                     "highGroupCode": ""},
                ],
            },
            "cateMList": {"groupInfoList": []},
            "cateSList": {"groupInfoList": []},
            "cateDList": {"groupInfoList": []},
        }
        out = TheHyundaiSourcingClient._build_category_tree(fixture)
        paths = {c["path"] for c in out["categories"]}
        assert "TopA" in paths
        assert "TopB" in paths
