# 삼바웨이브 소싱처/판매처 개발 가이드

> 클로드코드로 작업하는 팀원용. 이 문서를 컨텍스트로 제공하면 됩니다.

## 1. 전체 아키텍처

```
소싱처 수집 → CollectedProduct(DB) → 정책적용 → 마켓 전송
                     ↑                              ↓
              워룸/갱신 (가격/재고 최신화)      SambaOrder(주문수집)
```

### 핵심 파일 위치

| 구분 | 경로 | 역할 |
|------|------|------|
| 소싱 프록시 | `backend/domain/samba/proxy/{site}.py` | 소싱처 API 클라이언트 |
| 소싱 플러그인 | `backend/domain/samba/plugins/sourcing/{site}.py` | 플러그인 등록 (proxy 위임) |
| 판매 프록시 | `backend/domain/samba/proxy/{market}.py` | 마켓 API 클라이언트 |
| 판매 플러그인 | `backend/domain/samba/plugins/markets/{market}.py` | 플러그인 등록 (전송/수정/삭제) |
| Job 워커 | `backend/domain/samba/job/worker.py` | 수집/전송 백그라운드 실행 |
| 갱신 | `backend/domain/samba/collector/refresher.py` | 소싱처 가격/재고 최신화 |
| 고시정보 | `backend/domain/samba/proxy/notice_utils.py` | 마켓별 고시정보 생성 |
| 카테고리 | `backend/domain/samba/category/service.py` | AI 카테고리 매핑 |
| 주문 | `backend/api/v1/routers/samba/order.py` | 주문 동기화 + CS |

---

## 2. 소싱처 개발

### 2.1 수집 방식 결정

| 조건 | 방식 | worker.py 등록 |
|------|------|---------------|
| 공개 API/HTML 접근 가능 | `DIRECT_API_SITES` | 서버 HTTP 직접 호출 |
| 로그인/JS렌더링 필수 | `EXTENSION_SITES` | 확장앱 소싱큐 경유 |
| 로그인 + 쿠키 관리 | 전용 로직 | MUSINSA처럼 별도 분기 |

### 2.2 프록시 클라이언트 생성

파일: `backend/domain/samba/proxy/{site}.py`

```python
"""{사이트명} 소싱처 클라이언트."""
import httpx
import logging
from typing import Any

logger = logging.getLogger(__name__)

HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

class {Site}Client:
  """필수 메서드: search(), get_detail()"""

  async def search(self, keyword: str, max_count: int = 100, **kwargs) -> dict[str, Any]:
    """검색 → {"products": [...], "total": int}"""
    all_products = []
    # ... API/HTML 호출 ...
    return {"products": all_products, "total": len(all_products)}

  async def get_detail(self, product_id: str) -> dict[str, Any]:
    """상세 조회 → CollectedProduct flat 스키마"""
    # ... 상세 페이지 파싱 ...
    return {
      "site_product_id": product_id,
      "name": "",
      "brand": "",                    # ⚠️ string (object 아님)
      "original_price": 0,
      "sale_price": 0,
      "cost": 0,                      # 배송비 포함 원가
      "images": [],                   # ⚠️ string[] (flat URL 배열)
      "options": [],                  # [{no, name, price, stock, isSoldOut}]
      "style_code": "",               # ⚠️ 품번/SKU (상품명 조합에 사용)
      "source_site": "{Site}",
      "source_url": "https://...",
      "category": "",
      "category1": "",
      "category2": "",
      "category3": "",
      "detail_html": "",
      "detail_images": [],
      "material": "",
      "color": "",
      "manufacturer": "",
      "origin": "",
      "care_instructions": "",
      "quality_guarantee": "",
      "shipping_fee": 0,
    }

  @staticmethod
  def _map_item(item: dict) -> dict:
    """검색 API 응답 아이템 → CollectedProduct flat 스키마 변환."""
    # 검색 결과 1건을 정규화
    return {
      "site_product_id": str(item.get("id", "")),
      "name": item.get("name", ""),
      "brand": item.get("brand", ""),
      "original_price": int(item.get("originalPrice", 0)),
      "sale_price": int(item.get("salePrice", 0)),
      "images": [item.get("thumbnail", "")],
      "source_site": "{Site}",
      "source_url": f"https://example.com/product/{item.get('id', '')}",
    }
```

### 2.3 필수 스키마 규칙 (위반 시 전송 실패)

```
brand: string ("나이키")          ← object {id, name} 안 됨
images: string[] (URL 배열)       ← nested {thumbnail, product} 안 됨
options[].no: number              ← "optionNo" 안 됨
options[].price: 합산가격          ← additionalPrice 별도 안 됨
saleStatus: "in_stock"|"sold_out" ← object 안 됨
material: string                  ← array 안 됨
style_code: string                ← 품번/SKU (빈값 허용, 상품명 조합의 모델명에 사용)
```

### 2.4 플러그인 생성

파일: `backend/domain/samba/plugins/sourcing/{site}.py`

```python
"""{사이트명} 소싱처 플러그인."""
import logging
from typing import TYPE_CHECKING
from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
  from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)

class {Site}Plugin(SourcingPlugin):
  site_name = "{SITE}"       # 대문자
  concurrency = 3
  request_interval = 0.5

  async def search(self, keyword: str, **filters) -> list[dict]:
    from backend.domain.samba.proxy.{site} import {Site}Client
    client = {Site}Client()
    result = await self.safe_call(client.search(keyword, max_count=int(filters.get("max_count", 100))))
    return result.get("products", [])

  async def get_detail(self, site_product_id: str) -> dict:
    from backend.domain.samba.proxy.{site} import {Site}Client
    client = {Site}Client()
    return await self.safe_call(client.get_detail(site_product_id))

  async def refresh(self, product) -> "RefreshResult":
    from backend.domain.samba.collector.refresher import RefreshResult
    from backend.domain.samba.proxy.{site} import {Site}Client

    pid = getattr(product, "id", "")
    spid = getattr(product, "site_product_id", "")
    if not spid:
      return RefreshResult(product_id=pid, error="site_product_id 없음")

    try:
      client = {Site}Client()
      fresh = await client.get_detail(spid)
    except Exception as e:
      return RefreshResult(product_id=pid, error=str(e))

    new_sale = fresh.get("sale_price")
    old_sale = getattr(product, "sale_price", None)
    price_changed = new_sale is not None and new_sale != old_sale

    new_opts = fresh.get("options")
    stock_changed = False
    status = "in_stock"
    if new_opts and all(o.get("stock", 0) == 0 for o in new_opts):
      status = "sold_out"
      stock_changed = True

    return RefreshResult(
      product_id=pid,
      new_sale_price=new_sale,
      new_original_price=fresh.get("original_price"),
      new_cost=fresh.get("cost"),
      new_sale_status=status,
      new_options=new_opts,
      changed=price_changed,
      stock_changed=stock_changed,
    )
```

### 2.5 워커 등록

파일: `backend/domain/samba/job/worker.py` (130~145줄 근처)

```python
# 직접 API 소싱처 (서버 HTTP)
DIRECT_API_SITES = {"FashionPlus", "Nike", "Adidas", "{NewSite}"}  # ← 추가
# 확장앱 기반 소싱처 (소싱큐)
EXTENSION_SITES = {"ABCmart", "GrandStage", ...}
```

### 2.6 소싱 URL 등록 (주문 매칭용)

파일: `backend/api/v1/routers/samba/order.py` (715줄 근처)

```python
_sourcing_urls = {
    "MUSINSA": "https://www.musinsa.com/products/{}",
    "{NewSite}": "https://www.example.com/product/{}",  # ← 추가
}
```

### 2.7 기능별 인터벌 격리

수집 전용 인터벌 키를 사용하면 수집에서 429 받아도 전송/워룸 속도에 영향 없음:

```python
from backend.domain.samba.collector.refresher import get_interval_key
_ik = get_interval_key("MUSINSA", "collect")  # → "MUSINSA_collect"
await asyncio.sleep(_site_intervals.get(_ik, 1.0))
```

### 2.8 이미지 중복제거 패턴

```python
# 같은 이미지의 사이즈별 변형 중복제거 (패션플러스 패턴)
import re
seen: set[str] = set()
unique: list[str] = []
for img in all_images:
  fname = img.rsplit("/", 1)[-1]
  base = re.sub(r'^(plg[a-z]|thumb_|s_)', '', fname)  # 접두사 제거
  if base not in seen:
    seen.add(base)
    unique.append(img)
result["images"] = unique[:9]  # 최대 9장
```

### 2.9 추가수집 시 자동 상속

`create_collected_product()` 서비스 레이어에서 자동 처리 (코드 수정 불필요):
- 같은 그룹(search_filter_id)의 기존 상품에서 태그/SEO/정책/마켓가격 복사
- 신규 소싱처를 추가해도 자동 적용됨

---

## 3. 판매처(마켓) 개발

### 3.1 프록시 클라이언트

파일: `backend/domain/samba/proxy/{market}.py`

```python
class {Market}Client:
  """필수 메서드"""

  async def register_product(self, data: dict) -> dict:
    """상품 등록 → {"success": True, "data": {...}}"""

  async def update_product(self, product_no: str, data: dict) -> dict:
    """상품 수정"""

  async def delete_product(self, product_no: str) -> dict:
    """상품 삭제/판매중지"""

  @staticmethod
  def transform_product(product: dict, category_id: str = "") -> dict:
    """CollectedProduct → 마켓 API 형식 변환"""
```

### 3.2 마켓 플러그인

파일: `backend/domain/samba/plugins/markets/{market}.py`

```python
from backend.domain.samba.plugins.market_base import MarketPlugin

class {Market}Plugin(MarketPlugin):
  market_type = "{market}"     # 소문자 (smartstore, coupang, 11st ...)
  policy_key = "{마켓한글명}"   # "스마트스토어", "쿠팡" 등
  required_fields = ["name", "sale_price"]

  def transform(self, product: dict, category_id: str, **kwargs) -> dict:
    from backend.domain.samba.proxy.{market} import {Market}Client
    return {Market}Client.transform_product(product, category_id)

  async def execute(self, session, product, category_id, account, existing_no, **kwargs):
    """등록/수정 실행"""
    # 계정에서 인증 정보 추출
    additional = account.additional_fields or {}
    client = {Market}Client(additional["apiKey"], additional["apiSecret"])

    data = self.transform(product, category_id)

    if existing_no:
      return await client.update_product(existing_no, data)
    else:
      return await client.register_product(data)

  async def handle(self, session, product, category_id, account, existing_no, **kwargs):
    """MarketPlugin.handle() 오버라이드"""
    return await self.execute(session, product, category_id, account, existing_no)
```

### 3.3 고시정보 (notice_utils.py)

파일: `backend/domain/samba/proxy/notice_utils.py`

고시정보 타입 자동 판별:
1. 매핑된 마켓 카테고리 ID → `_detect_group_from_ss_category()`
2. 상품 카테고리 필드 → `detect_notice_group()`
3. 상품명/브랜드 키워드 → fallback 추론

```
WEAR   → 의류 (소재/색상/치수/제조사/세탁)
SHOES  → 신발 (소재/색상/치수/제조사/세탁)
BAG    → 가방
ETC    → 기타 (itemName[:50] 주의)
```

### 3.4 카테고리 매핑

- AI 매핑은 **동기화된 실제 마켓 카테고리에서만** 선택 (가상 카테고리 생성 금지)
- `MARKET_CATEGORIES` (하드코딩) vs DB 동기화 → DB 우선
- 스마트스토어는 DB에 4964개 동기화됨

### 3.5 상품명 제한

| 마켓 | 제한 |
|------|------|
| 스마트스토어 | 49자 |
| 쿠팡 | 100자 |
| 기타 | 100자 |

### 3.6 SEO 키워드

- 생성 개수: **2개** (태그사전 검증 통과한 것만)
- 전송 시 `seo_keywords[:2]`를 공백 연결

---

## 4. 절대 하지 말 것

### 소싱처
- ❌ `__init__.py`, `market_base.py`, `sourcing_base.py`, `collector/` 폴더 수정 금지
- ❌ `_site_intervals["MUSINSA"]` 직접 사용 → `get_interval_key()` 사용
- ❌ 하드코딩 인터벌 → `_site_intervals` 적응형 사용
- ❌ brand를 object로 반환 → string만
- ❌ images를 nested로 반환 → flat string[] 만

### 판매처
- ❌ AI 카테고리 매핑에서 목록 외 카테고리 생성
- ❌ 고시정보 `itemName`에 50자 초과 값
- ❌ 상품명에 마켓 제한 초과 문자열

### 공통
- ❌ `create_collected_product()` 대신 직접 `repo.create_async()` 호출 (그룹 속성 상속 누락)
- ❌ 전송 성공 후 `market_product_nos` 저장 누락 (주문 매칭 불가)
- ❌ `source_url` 저장 누락 (원문링크 미작동)

---

## 5. 브랜치 규칙

```
feature/{site}-plugin   → plugins/markets/{site}.py + proxy/{site}.py 만 수정
feature/{site}-sourcing → plugins/sourcing/{site}.py + proxy/{site}.py 만 수정
```

위 파일 외 수정 필요 시 → "이 파일도 수정이 필요합니다. 팀장에게 확인하세요"

---

## 6. 테스트 방법

```bash
# 백엔드 실행
cd backend && .venv/Scripts/python.exe run.py

# 프록시 클라이언트 단독 테스트
cd backend && .venv/Scripts/python.exe -c "
import asyncio
from backend.domain.samba.proxy.{site} import {Site}Client
async def main():
  client = {Site}Client()
  # 검색
  result = await client.search('나이키', max_count=5)
  print(f'검색: {len(result[\"products\"])}건')
  # 상세
  if result['products']:
    detail = await client.get_detail(result['products'][0]['site_product_id'])
    print(f'상세: {detail.get(\"name\", \"\")}')
    print(f'품번: {detail.get(\"style_code\", \"\")}')
    print(f'옵션: {len(detail.get(\"options\", []))}개')
    print(f'이미지: {len(detail.get(\"images\", []))}장')
asyncio.run(main())
"
```

---

## 7. 참고: 기존 구현 참조

| 소싱처 | 참조 파일 | 특이사항 |
|--------|----------|---------|
| 무신사 | `proxy/musinsa.py` | 쿠키 인증, 최대혜택가 5단계 계산, similarNo 그룹핑 |
| 패션플러스 | `proxy/fashionplus.py` | 검색API+상세HTML+옵션API 3단계, SKU→style_code, 이미지 사이즈 중복제거 |
| Nike | `proxy/nike.py` | __NEXT_DATA__ 파싱, styleCode 추출, PDP HTML |
| KREAM | `proxy/kream.py` | 확장앱 큐 기반, chrome.tabs.update(active:true) 필수 |
| 스마트스토어 | `proxy/smartstore.py` | OAuth2+bcrypt, 카탈로그 매칭, 이미지 업로드 |
| 11번가 | `proxy/elevenst.py` | XML 포맷, openapikey 인증 |
| 쿠팡 | `proxy/coupang.py` | HMAC 서명, 카테고리 meta API |

---

*최종 업데이트: 2026-03-29*
