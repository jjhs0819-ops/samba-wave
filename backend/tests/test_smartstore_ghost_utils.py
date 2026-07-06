"""스마트스토어 유령(역고아) 판정 로직 테스트 — ghost_utils.judge_smartstore_stale.

시나리오:
1. Naver에 살아있는 매핑 → 역고아 아님
2. Naver에 없고 같은 품번도 없음 → 역고아 (매핑 해제 대상)
3. originNo는 죽었지만 같은 품번이 살아있음 → 재연결 (기존엔 무조건 스킵 → 유령 영구 방치)
4. 페이지 누락 시 → 판정 전체 보류 (정상 매핑 해제 사고 방지)
5. 재연결 안전 가드 — 주인 있는 상품(claimed) → 역고아, 품번 중복(모호) → 보류
"""

from pathlib import Path

from backend.domain.samba.shipment.ghost_utils import judge_smartstore_stale

SHIPMENT_PY = (
    Path(__file__).resolve().parents[1] / "backend/api/v1/routers/samba/shipment.py"
)


def _info(db_id: str, style: str = "") -> dict:
    return {
        "db_id": db_id,
        "style_code": style,
        "mapped_origin_no": f"origin-{db_id}",
        "product_name": f"상품{db_id}",
    }


class TestJudgeSmartstoreStale:
    def test_alive_mapping_is_not_stale(self):
        stale, relinks, ambig = judge_smartstore_stale(
            {"100": _info("a")},
            naver_nos={"100"},
            naver_mgmt_map={},
            pages_incomplete=False,
        )
        assert stale == [] and relinks == [] and ambig == []

    def test_dead_mapping_without_style_match_is_stale(self):
        stale, relinks, ambig = judge_smartstore_stale(
            {"100": _info("a", style="SKU-1")},
            naver_nos=set(),
            naver_mgmt_map={},
            pages_incomplete=False,
        )
        assert [s["db_id"] for s in stale] == ["a"]
        assert relinks == [] and ambig == []

    def test_dead_origin_with_live_style_becomes_relink(self):
        """핵심 수정 — 같은 품번이 살아있으면 방치(스킵)가 아니라 재연결."""
        stale, relinks, ambig = judge_smartstore_stale(
            {"100": _info("a", style="SKU-1")},
            naver_nos={"200"},  # 100은 죽었고 200이 새 상품
            naver_mgmt_map={"SKU-1": {"origin_no": "200", "channel_no": "300"}},
            pages_incomplete=False,
        )
        assert stale == [] and ambig == []
        assert len(relinks) == 1
        assert relinks[0]["db_id"] == "a"
        assert relinks[0]["new_origin_no"] == "200"
        assert relinks[0]["new_channel_no"] == "300"

    def test_channel_no_match_is_not_stale(self):
        """DB에 channelProductNo로 매핑돼 있어도 naver_nos에 채널번호가 들어있으면 생존."""
        stale, relinks, ambig = judge_smartstore_stale(
            {"300": _info("a")},
            naver_nos={"200", "300"},  # 300 = channelProductNo
            naver_mgmt_map={},
            pages_incomplete=False,
        )
        assert stale == [] and relinks == [] and ambig == []

    def test_incomplete_pages_suspends_all_judgement(self):
        """페이지 누락 시 역고아/재연결 판정 전부 보류 — 오판으로 정상 매핑 해제 방지."""
        stale, relinks, ambig = judge_smartstore_stale(
            {"100": _info("a"), "200": _info("b", style="SKU-1")},
            naver_nos=set(),
            naver_mgmt_map={"SKU-1": {"origin_no": "999", "channel_no": ""}},
            pages_incomplete=True,
        )
        assert stale == [] and relinks == [] and ambig == []

    def test_relink_without_origin_no_falls_back_to_stale(self):
        """mgmt 맵에 origin_no가 비어있으면 재연결 불가 → 역고아로 처리."""
        stale, relinks, ambig = judge_smartstore_stale(
            {"100": _info("a", style="SKU-1")},
            naver_nos=set(),
            naver_mgmt_map={"SKU-1": {"origin_no": "", "channel_no": "300"}},
            pages_incomplete=False,
        )
        assert [s["db_id"] for s in stale] == ["a"]
        assert relinks == [] and ambig == []

    def test_mixed_batch(self):
        stale, relinks, ambig = judge_smartstore_stale(
            {
                "1": _info("alive"),
                "2": _info("ghost", style="SKU-G"),
                "3": _info("moved", style="SKU-M"),
            },
            naver_nos={"1"},
            naver_mgmt_map={"SKU-M": {"origin_no": "33", "channel_no": "44"}},
            pages_incomplete=False,
        )
        assert [s["db_id"] for s in stale] == ["ghost"]
        assert [r["db_id"] for r in relinks] == ["moved"]
        assert ambig == []


class TestRelinkSafetyGuards:
    """재연결 안전 가드 — 실마켓 매핑 변경이므로 보수적으로."""

    def test_claimed_target_becomes_stale_not_relink(self):
        """재연결 대상 Naver 상품을 다른 DB 상품이 이미 매핑 중(주인 있음) →
        이 죽은 매핑은 찌꺼기 = 역고아. 이중 매핑(#534 identity 충돌) 방지."""
        stale, relinks, ambig = judge_smartstore_stale(
            {"100": _info("a", style="SKU-1")},
            naver_nos={"200"},
            naver_mgmt_map={"SKU-1": {"origin_no": "200", "channel_no": "300"}},
            pages_incomplete=False,
            claimed_nos={"100", "200"},  # 200은 다른 DB 상품이 이미 점유
        )
        assert [s["db_id"] for s in stale] == ["a"]
        assert relinks == [] and ambig == []

    def test_claimed_channel_also_blocks_relink(self):
        """채널번호가 점유돼 있어도 재연결 금지."""
        stale, relinks, ambig = judge_smartstore_stale(
            {"100": _info("a", style="SKU-1")},
            naver_nos={"200"},
            naver_mgmt_map={"SKU-1": {"origin_no": "200", "channel_no": "300"}},
            pages_incomplete=False,
            claimed_nos={"100", "300"},  # 채널 300 점유
        )
        assert [s["db_id"] for s in stale] == ["a"]
        assert relinks == [] and ambig == []

    def test_duplicate_dead_style_is_ambiguous_no_action(self):
        """같은 품번의 죽은 매핑 2개 → 어느 쪽을 연결할지 모호 → 둘 다 보류(무조치)."""
        stale, relinks, ambig = judge_smartstore_stale(
            {
                "100": _info("a", style="SKU-1"),
                "101": _info("b", style="SKU-1"),
            },
            naver_nos={"200"},
            naver_mgmt_map={"SKU-1": {"origin_no": "200", "channel_no": "300"}},
            pages_incomplete=False,
            claimed_nos={"100", "101"},
        )
        assert stale == [] and relinks == []
        assert sorted(x["db_id"] for x in ambig) == ["a", "b"]

    def test_unclaimed_unique_style_still_relinks(self):
        """가드에 안 걸리는 정상 케이스는 여전히 재연결."""
        stale, relinks, ambig = judge_smartstore_stale(
            {"100": _info("a", style="SKU-1")},
            naver_nos={"200"},
            naver_mgmt_map={"SKU-1": {"origin_no": "200", "channel_no": "300"}},
            pages_incomplete=False,
            claimed_nos={"100"},  # 자기 자신(죽은 번호)만 — 점유 아님
        )
        assert stale == [] and ambig == []
        assert [r["db_id"] for r in relinks] == ["a"]


class TestCleanupOrphansSourceContracts:
    """cleanup-orphans 엔드포인트 정적 계약 (회귀 가드)."""

    def test_commit_before_naver_paging(self):
        """네이버 페이징(수십 초~수 분) 전에 초기 조회 트랜잭션을 닫아야 함.
        안 닫으면 idle-in-transaction이 IIT 타임아웃(300s)/kill_idle_tx(150s)에
        잘려 "Database error" 500 전체 실패."""
        src = SHIPMENT_PY.read_text(encoding="utf-8")
        idx_load = src.find("all_db_products = prod_result.all()")
        assert idx_load != -1, "cleanup-orphans 상품 로드 블록 미발견"
        idx_paging = src.find('"/v1/products/search"', idx_load)
        assert idx_paging != -1, "cleanup-orphans 네이버 페이징 블록 미발견"
        idx_commit = src.find("await session.commit()", idx_load)
        assert idx_commit != -1 and idx_commit < idx_paging, (
            "회귀 — 초기 조회 후 네이버 페이징 전 tx 커밋 누락 "
            "(idle-in-transaction 강제종료 → Database error 500 재발)"
        )

    def test_orphan_judgement_uses_full_catalog(self):
        """고아(Naver 실삭제) 판정은 화면 필터와 무관하게 전체 카탈로그 기준이어야 함.
        필터 부분집합과 비교하면 필터 밖 정상 등록상품이 Naver에서 오삭제된다."""
        src = SHIPMENT_PY.read_text(encoding="utf-8")
        assert "filter_ids" in src, (
            "회귀 — 화면 필터를 역고아 범위 한정에만 쓰는 filter_ids 로직 제거됨"
        )
        # 상품 로드 쿼리에 product_ids 직접 where 가 되살아나면 안 됨
        idx_q = src.find("# 고아(Naver 삭제) 판정 기준은 **항상 전체 카탈로그**")
        assert idx_q != -1, (
            "회귀 — 고아 판정 전체 카탈로그 원칙 주석/로직 제거됨 "
            "(화면 필터 상태로 실행 시 Naver 오삭제 위험)"
        )
