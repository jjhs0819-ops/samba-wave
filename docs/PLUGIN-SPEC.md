# 플러그인 인터페이스 스펙

> 소싱처/마켓 플러그인을 만들 때 이 규격을 따른다

---

## 소싱 플러그인

### 파일 위치
```
backend/domain/samba/plugins/sourcing/
  base.py          ← 인터페이스 (수정 금지)
  musinsa.py       ← 무신사 플러그인
  kream.py         ← 크림 플러그인
  oliveyoung.py    ← 올리브영 플러그인
  ...
```

### 인터페이스

```python
class SourcingPlugin:
    """소싱처 플러그인 기본 클래스. 모든 소싱처는 이걸 상속한다."""

    site_name: str           # "MUSINSA", "KREAM" 등
    base_url: str            # "https://www.musinsa.com"
    default_interval: float  # 요청 간격 (초). 기본 1.0

    async def search(self, keyword: str, page: int = 1, size: int = 100) -> SearchResult:
        """키워드 검색. 상품 목록 반환."""
        raise NotImplementedError

    async def get_detail(self, product_id: str) -> ProductDetail:
        """상품 상세 정보 조회."""
        raise NotImplementedError

    async def check_stock(self, product_id: str) -> StockResult:
        """재고/가격 확인 (갱신용)."""
        raise NotImplementedError
```

### 데이터 모델

```python
class SearchResult:
    items: list[dict]        # [{"id": "123", "name": "...", "price": 39000}, ...]
    total: int               # 전체 검색 결과 수
    has_next: bool           # 다음 페이지 존재 여부

class ProductDetail:
    name: str
    brand: str
    original_price: int
    sale_price: int
    cost: int                # 원가 (최대혜택가 또는 판매가)
    images: list[str]        # [대표이미지, 추가이미지...]
    detail_images: list[str] # 상세페이지 이미지
    options: list[dict]      # [{"name": "M", "stock": 10, "price": 39000}, ...]
    category: str            # "상의 > 반소매 티셔츠"
    sale_status: str         # "in_stock" | "sold_out" | "preorder"
    # ... 기타 필드

class StockResult:
    sale_price: int | None
    cost: int | None
    options: list[dict] | None
    sale_status: str         # "in_stock" | "sold_out"
    images: list[str] | None # 변경 시에만
```

### 플러그인 작성 예시

```python
# backend/domain/samba/plugins/sourcing/oliveyoung.py

from .base import SourcingPlugin, SearchResult, ProductDetail, StockResult

class OliveYoungPlugin(SourcingPlugin):
    site_name = "OliveYoung"
    base_url = "https://www.oliveyoung.co.kr"
    default_interval = 1.5  # 올리브영은 좀 더 느리게

    async def search(self, keyword, page=1, size=100):
        # 검색 API 호출
        ...
        return SearchResult(items=items, total=total, has_next=has_next)

    async def get_detail(self, product_id):
        # 상세 API 호출
        ...
        return ProductDetail(name=name, brand=brand, ...)

    async def check_stock(self, product_id):
        # 재고 확인
        ...
        return StockResult(sale_price=price, cost=cost, ...)
```

### 플러그인 등록

```python
# backend/domain/samba/plugins/sourcing/__init__.py

from .musinsa import MusinsaPlugin
from .kream import KreamPlugin
from .oliveyoung import OliveYoungPlugin

# 이름으로 플러그인 조회
SOURCING_PLUGINS = {
    "MUSINSA": MusinsaPlugin,
    "KREAM": KreamPlugin,
    "OliveYoung": OliveYoungPlugin,
}

def get_sourcing_plugin(site_name: str) -> SourcingPlugin:
    cls = SOURCING_PLUGINS.get(site_name)
    if not cls:
        raise ValueError(f"미지원 소싱처: {site_name}")
    return cls()
```

---

## 마켓 플러그인

### 파일 위치
```
backend/domain/samba/plugins/market/
  base.py          ← 인터페이스 (수정 금지)
  smartstore.py    ← 스마트스토어 플러그인
  coupang.py       ← 쿠팡 플러그인
  elevenst.py      ← 11번가 플러그인
  ...
```

### 인터페이스

```python
class MarketPlugin:
    """마켓 플러그인 기본 클래스. 모든 판매처는 이걸 상속한다."""

    market_type: str         # "smartstore", "coupang" 등
    market_name: str         # "스마트스토어", "쿠팡" 등

    async def authenticate(self, credentials: dict) -> bool:
        """인증. 성공 시 True."""
        raise NotImplementedError

    async def register(self, product: dict, category_id: str) -> RegisterResult:
        """상품 등록. 마켓 상품번호 반환."""
        raise NotImplementedError

    async def update(self, product_no: str, product: dict, update_items: list[str]) -> bool:
        """상품 수정. 가격/재고/이미지 등."""
        raise NotImplementedError

    async def delete(self, product_no: str) -> bool:
        """상품 삭제/판매중지."""
        raise NotImplementedError

    async def sync_orders(self, since: datetime) -> list[dict]:
        """주문 수집."""
        raise NotImplementedError

    def transform_product(self, product: dict, category_id: str) -> dict:
        """상품 데이터 → 마켓 API 형식 변환."""
        raise NotImplementedError
```

### 데이터 모델

```python
class RegisterResult:
    success: bool
    product_no: str          # 마켓 상품번호
    origin_product_no: str   # 원본 상품번호 (스마트스토어)
    message: str             # 성공/실패 메시지
```

---

## 플러그인 개발 규칙

1. **파일 1개 = 플러그인 1개** — 다른 플러그인 import 금지
2. **최대 300줄** — 넘으면 헬퍼 파일 분리 (같은 폴더)
3. **base.py 수정 금지** — 인터페이스 변경은 리드 승인 필요
4. **테스트 필수** — `tests/plugins/test_{site_name}.py` 작성
5. **에러 처리** — RateLimitError, AuthError 등 공통 예외 사용
6. **로깅** — `logger.info/warning/error` 사용, print 금지
