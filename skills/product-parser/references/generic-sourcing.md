# 통합 소싱 큐 (Generic Sourcing) 레퍼런스

## 개요

확장앱 기반 범용 상품 수집 시스템.
KREAM 큐 패턴과 동일하되, 여러 사이트를 하나의 큐로 통합 관리한다.

| 항목 | 내용 |
|------|------|
| **수집 방식** | 확장앱 큐 + DOM 스크래핑 |
| **갱신 파서** | `_parse_generic_stub` (스텁 — 실제 갱신 미구현) |
| **참조 파일** | `backend/backend/domain/samba/proxy/sourcing_queue.py`, `extension/background.js` |

## 지원 사이트 (7개)

| 사이트 코드 | 라벨 | 검색 URL | 상세 URL |
|------------|------|---------|---------|
| `ABCmart` | ABC마트 | `https://www.a-rt.com/display/search-word/result?searchWord={keyword}` | `https://www.a-rt.com/product?prdtNo={product_id}` |
| `GrandStage` | 그랜드스테이지 | `https://www.a-rt.com/...&channel=10002` | `https://www.a-rt.com/product?prdtNo={product_id}&tChnnlNo=10002` |
| `OKmall` | OKmall | `https://www.okmall.com/products/list?keyword={keyword}` | `https://www.okmall.com/products/detail/{product_id}` |
| `LOTTEON` | 롯데ON | `https://www.lotteon.com/search/...?q={keyword}` | `https://www.lotteon.com/product/productDetail.lotte?spdNo={product_id}` |
| `GSShop` | GSShop | `https://www.gsshop.com/search/searchMain.gs?tq={keyword}` | `https://www.gsshop.com/prd/prd.gs?prdid={product_id}` |
| `ElandMall` | 이랜드몰 | `https://www.elandmall.com/search/search.action?kwd={keyword}` | `https://www.elandmall.com/goods/goods.action?goodsNo={product_id}` |
| `SSF` | SSF샵 | `https://www.ssfshop.com/search?keyword={keyword}` | `https://www.ssfshop.com/goods/{product_id}` |

> **참고:** ABCmart와 GrandStage는 동일 도메인(a-rt.com)이며 channel 파라미터로 구분

## 스텁 전용 사이트 (3개, 소싱큐 미지원)

| 사이트 코드 | 라벨 | 상태 |
|------------|------|------|
| `Nike` | Nike | refresher 스텁만 등록, 전용 프록시 파일 존재 |
| `Adidas` | Adidas | refresher 스텁만 등록, 전용 프록시 파일 존재 |
| `FashionPlus` | 패션플러스 | refresher 스텁만 등록, 전용 프록시 파일 존재 |

## 큐 동작 흐름

```
[백엔드]
SourcingQueue.add_search_job(site, keyword)
  → requestId 생성
  → queue에 {requestId, site, type:"search", url, keyword} 추가
  → asyncio.Future 생성 + resolvers에 등록
  → (requestId, future) 반환

SourcingQueue.add_detail_job(site, product_id)
  → queue에 {requestId, site, type:"detail", url, productId} 추가
  → (requestId, future) 반환

[확장앱]
폴링: GET /api/v1/samba/proxy/sourcing/queue
  → SourcingQueue.get_next_job() → {hasJob, requestId, site, type, url, ...}

수집 완료: POST /api/v1/samba/proxy/sourcing/result
  → SourcingQueue.resolve_job(requestId, data) → Future.set_result(data)
```

## 확장앱 범용 DOM 파싱 (`handleSourcingJob` in background.js)

```
1. 탭 생성 → 로드 대기
2. 타입 확인:
   a) type="search" → extractSearchResults(tabId, site)
   b) type="detail" → extractDetailData(tabId, site, productId)
3. DOM 파싱 전략 (우선순위):
   a) JSON-LD (<script type="application/ld+json">)
   b) Open Graph 메타 태그 (og:title, og:image, og:price)
   c) 순수 DOM 파싱 (사이트별 selector)
4. 검색: a[href] 링크 매칭 (사이트별 regex) → 상품 카드 컨테이너 추출
5. 상세: 이미지, 가격, 옵션, 상세설명 추출
6. 탭 닫기 → 결과 전송
```

## 범용 스텁 파서 (refresher.py)

```python
async def _parse_generic_stub(product) -> RefreshResult:
  """실제 파싱 없음 — 기존 값 유지, changed=False 반환."""
  return RefreshResult(
    product_id=product.id,
    new_sale_price=product.sale_price,
    new_original_price=product.original_price,
    new_cost=product.cost,
    new_sale_status=product.sale_status,
    changed=False,
  )
```

> 스텁 파서는 가격/재고 갱신을 하지 않는다.
> 실제 갱신이 필요하면 사이트별 전용 파서를 구현해야 한다.

## 새 사이트 추가 방법

### 소싱큐 지원 사이트 추가
```python
# 1. sourcing_queue.py에 URL 템플릿 추가
SITE_SEARCH_URLS["NewSite"] = "https://newsite.com/search?q={keyword}"
SITE_DETAIL_URLS["NewSite"] = "https://newsite.com/product/{product_id}"

# 2. refresher.py SITE_PARSERS에 스텁 등록
SITE_PARSERS["NewSite"] = _parse_generic_stub

# 3. frontend collector page에 드롭다운 추가
# 4. background.js에 사이트별 DOM selector 추가 (필요시)
```

### 전용 파서 개발 (스텁 → 활성)
```python
# refresher.py에 전용 함수 작성
async def _parse_newsite(product) -> RefreshResult:
  # HTTP 요청 또는 확장앱 큐로 최신 데이터 수집
  # 가격/재고 변동 감지
  # RefreshResult 반환

# SITE_PARSERS 업데이트
SITE_PARSERS["NewSite"] = _parse_newsite
```

## 프론트엔드 UI 컬러 매핑

```typescript
const SITE_COLORS = {
  MUSINSA:     '#4C9AFF',  // 파랑
  KREAM:       '#51CF66',  // 초록
  FashionPlus: '#CC5DE8',  // 보라
  Nike:        '#FF6B6B',  // 빨강
  Adidas:      '#FFD93D',  // 노랑
  ABCmart:     '#FF8C00',  // 주황
  GrandStage:  '#20C997',  // 청록
  OKmall:      '#F06595',  // 핑크
  LOTTEON:     '#E10044',  // 진빨강
  GSShop:      '#6B5CE7',  // 자주
  ElandMall:   '#4ECDC4',  // 청록2
  SSF:         '#845EF7',  // 연보라
}
```
