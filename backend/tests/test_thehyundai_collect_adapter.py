"""더현대Hi 잡워커 수집 어댑터(search/get_detail) 회귀 테스트.

배경: 잡워커 _collect_direct_api 는 client.search(keyword, max_count, **kwargs)
→ {"products": [...], "total": N} 인터페이스를 요구한다 (단일 페이지
search_products 와 다름). 그룹 URL 파싱 폴백과 페이징 집계를 검증한다.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.proxy.thehyundai_sourcing import TheHyundaiSourcingClient


def _fake_items(start: int, n: int) -> list[dict]:
    return [
        {"site_product_id": f"40B{start + i:07d}", "name": f"상품{start + i}"}
        for i in range(n)
    ]


class _PagedClient(TheHyundaiSourcingClient):
    """search_products 를 페이지 응답 시뮬레이션으로 대체."""

    def __init__(self, pages: dict[int, list[dict]]):
        super().__init__()
        self._pages = pages
        self.calls: list[dict] = []

    async def search_products(self, keyword: str, **filters):
        self.calls.append({"keyword": keyword, **filters})
        return self._pages.get(int(filters.get("page") or 1), [])


class TestSearchAdapter:
    async def test_single_page(self) -> None:
        client = _PagedClient({1: _fake_items(1, 10)})
        result = await client.search("나이키", max_count=100)
        assert result["total"] == 10
        assert len(result["products"]) == 10
        assert result["products"][0]["site_product_id"] == "40B0000001"

    async def test_pagination_until_max_count(self) -> None:
        pages = {1: _fake_items(1, 36), 2: _fake_items(37, 36), 3: _fake_items(73, 36)}
        client = _PagedClient(pages)
        result = await client.search("나이키", max_count=50)
        assert result["total"] == 50
        # 2페이지에서 max_count 도달 → 3페이지 미호출
        assert max(c["page"] for c in client.calls) == 2

    async def test_stops_on_empty_page(self) -> None:
        client = _PagedClient({1: _fake_items(1, 36), 2: []})
        result = await client.search("나이키", max_count=999)
        assert result["total"] == 36

    async def test_duplicate_page_terminates(self) -> None:
        # 사이트가 마지막 페이지를 반복 반환하는 경우 무한루프 방지
        same = _fake_items(1, 36)
        client = _PagedClient({1: same, 2: same, 3: same})
        result = await client.search("나이키", max_count=999)
        assert result["total"] == 36
        assert max(c["page"] for c in client.calls) == 2  # 중복 감지 즉시 종료

    async def test_group_url_parsing_fallback(self) -> None:
        # 워커 외 호출자가 그룹 URL 원문을 넘겨도 q/flBrand/flCate 추출
        client = _PagedClient({1: _fake_items(1, 5)})
        url = (
            "https://hi.thehyundai.com/search?q=%EB%82%98%EC%9D%B4%ED%82%A4"
            "&flBrand=101047&flCate=400004&includeSoldOut=1"
        )
        result = await client.search(url, max_count=10)
        assert result["total"] == 5
        call = client.calls[0]
        assert call["keyword"] == "나이키"
        assert call["flBrand"] == "101047"
        assert call["flCate"] == "400004"
        assert call["includeSoldOut"] is True

    async def test_worker_search_kwargs_passthrough(self) -> None:
        # 워커 _search_kwargs 의 flBrand/flCate 채택 + 타 소싱처 키 무시
        client = _PagedClient({1: _fake_items(1, 3)})
        result = await client.search(
            "나이키",
            max_count=10,
            flCate="400004",
            category1Id="123",  # 패션플러스용 키 — 무시돼야 함
            brand_name="나이키",  # 패션플러스용 키 — 무시돼야 함
        )
        assert result["total"] == 3
        call = client.calls[0]
        assert call["flCate"] == "400004"
        assert "category1Id" not in call
        assert "brand_name" not in call


class TestGetDetailAlias:
    async def test_alias_delegates(self) -> None:
        client = TheHyundaiSourcingClient()
        captured = {}

        async def _fake_detail(pid):
            captured["pid"] = pid
            return {"site_product_id": pid}

        client.get_product_detail = _fake_detail  # type: ignore[method-assign]
        detail = await client.get_detail("40B0696270", shared_client=None)
        assert captured["pid"] == "40B0696270"
        assert detail["site_product_id"] == "40B0696270"
