# KREAM 수집 레퍼런스

## 개요

| 항목 | 내용 |
|------|------|
| **사이트 코드** | `KREAM` |
| **수집 방식** | 확장앱 큐 + DOM 스크래핑 (상세), HTTP SSR 파싱 (검색/기본) |
| **갱신 파서** | `_parse_kream` (활성) |
| **인증** | Bearer 토큰 + 쿠키 |
| **참조 파일** | `backend/backend/domain/samba/proxy/kream.py`, `extension/background.js` |

## 수집 방식 2가지

### 1. HTTP SSR 파싱 (확장앱 불필요)

검색과 기본 상품 정보는 서버에서 직접 HTTP로 수집 가능.

```
검색: GET https://kream.co.kr/search?keyword={keyword}&tab=products
  → HTML 파싱 → <a href="/products/{id}"> 블록 추출
  → og:title, og:image, 가격 텍스트 추출

상세: GET https://kream.co.kr/products/{product_id}
  → og:title → 상품명
  → og:image → 대표이미지
  → JSON-LD "price" → 가격
```

**한계:** 사이즈별 옵션/가격, 배송비, 상세 이미지 등은 JS 렌더링 필요 → 확장앱 필요

### 2. 확장앱 큐 방식 (상세 수집)

```
서버: KreamClient.collect_queue에 job 등록
  → asyncio.Future 생성 + resolvers에 등록
  → wait_for(future, timeout=90초)

확장앱: 30초 폴링 → job 수신
  → 탭 생성(active:false) → 로드 대기(30초)
  → __NUXT__ 데이터 추출 (jsonLd)
  → 탭 active 전환 (visibilityState visible)
  → 구매하기 버튼 클릭 (텍스트 매칭)
  → .select_item DOM 파싱 → 사이즈 옵션 읽기
  → 각 사이즈별 바텀시트 열어 배송가격 파싱
  → 결과 전송 (POST /api/v1/samba/proxy/kream/collect-result)
  → 서버 Future resolve
```

## 큐 구조 (클래스 레벨, 서버 재시작 시 초기화)

```python
class KreamClient:
  # 수집 큐
  collect_queue: list[dict] = []      # [{requestId, productId, url}]
  collect_resolvers: dict = {}        # {requestId: asyncio.Future}

  # 검색 큐
  search_queue: list[dict] = []       # [{requestId, keyword, url}]
  search_resolvers: dict = {}         # {requestId: asyncio.Future}
```

## 확장앱 수집 상세 (`handleCollectJob` in background.js)

```
1. 백그라운드 탭 생성 (active:false, 로그인 세션 공유)
2. 탭 로드 대기 (30초 timeout)
3. __NUXT__ 데이터 추출 (jsonLd) → 기본 상품 정보
4. ★ 탭 active 전환 (visibilityState visible 만들기)
5. "구매하기" 버튼 텍스트 매칭 → 클릭
6. 사이즈 옵션 DOM 읽기 (.select_item):
   [
     { name: "230", priceText: "123,000원" 또는 "구매입찰" },
     ...
   ]
   → stock: 숫자가 있으면 1, "구매입찰"이면 0
7. 각 사이즈별 배송가격 수집:
   a. .select_item[i] 클릭
   b. 바텀시트 대기 폴링 (최대 5초)
   c. 빠른배송/일반배송 가격 텍스트 파싱
   d. 바텀시트 닫기
8. 이미지 프록시 URL로 변환
9. content script로 기본정보 수집
10. 탭 닫기
11. 결과 서버 전송
```

## 데이터 변환 (`transform_to_product`)

### 옵션 추출
```python
sizes = item.sales_options or item.sizes or item.product_options or item.options
for s in sizes:
  name = s.option or s.size or s.name or s.option_name
  ask  = s.buy_now_price or s.immediate_purchase_price or s.ask or s.price
  bid  = s.sell_now_price or s.immediate_sell_price or s.bid
  last = s.last_sale_price or s.last_price

  options.append({
    "name": name,
    "price": ask,
    "stock": 0 if (is_sold_out or ask == 0) else 1,
    "isSoldOut": is_sold_out,
    "kreamAsk": ask,      # 즉시구매가
    "kreamBid": bid,      # 즉시판매가
    "kreamLastSale": last, # 최근거래가
    "kreamFastPrice": 0,   # 빠른배송가
    "kreamNormalPrice": 0, # 일반배송가
  })
```

### 가격 결정
```python
ask_prices = [o.kreamAsk for o in options if o.kreamAsk > 0]
min_ask = min(ask_prices) if ask_prices else 0
sale_price = min_ask if min_ask > 0 else retail_price
```

### kream_data (KREAM 특화 저장)
```json
{
  "modelNo": "DQ3985-104",
  "releaseDate": "2024-01-15",
  "retailPrice": 169000,
  "askPrices": {
    "230": { "fast": 0, "normal": 0, "general": 180000 }
  },
  "bidPrices": {
    "230": { "general": 150000 }
  },
  "lastSalePrices": {
    "230": { "price": 175000, "date": "2026-03-20" }
  },
  "tradeVolume": 1234,
  "wishCount": 5678,
  "saleTypes": { "general": true, "storage": false, "grade95": false }
}
```

## 이미지 처리

### 프록시 URL 변환
```
KREAM 이미지 URL → /api/v1/samba/proxy/kream/image-proxy?url={encoded_url}
이유: CORS 정책으로 외부에서 직접 접근 불가
```

### 프록시 구현 (`proxy_image`)
```python
async def proxy_image(url: str) -> tuple[bytes, str]:
  # Referer: https://kream.co.kr/ 헤더 필수
  # 응답: (image_bytes, content_type)
```

## 갱신 파서 (`_parse_kream` in refresher.py)

```
1. KreamClient.collect_queue에 job 등록
2. asyncio.Future 생성
3. 90초 timeout 대기
4. 확장앱 결과 수신 → Future resolve
5. 결과에서 추출:
   - options → 사이즈별 가격/재고
   - salePrice: min(ask_prices) or retail_price
   - originalPrice: retail_price
   - sale_status: 재고 있는 옵션 존재 → in_stock, 없으면 sold_out
6. RefreshResult 반환
```

## 인증

### 로그인 (2단계 시도)
```
1차: POST https://kream.co.kr/api/session {email, password}
2차: POST https://kream.co.kr/auth/login {email, password}
→ access_token 획득 → self.token 저장
```

### 인증 상태 확인
```
GET https://kream.co.kr/api/users/me
Headers: Authorization: Bearer {token}
```

## 매도 입찰 (Sell API)

```
등록: POST /api/asks {product_id, size, price, sale_type}
수정: PUT  /api/asks/{ask_id} {price}
취소: DELETE /api/asks/{ask_id}
목록: GET  /api/asks/me
```

## 체크리스트 특이사항 (autoresearch 참고)

| 항목 | KREAM 특성 |
|------|-----------|
| `detailImages` | 항상 빈 배열 `[]` — 상세 이미지 수집 미지원 |
| `detailHtml` | 항상 빈 문자열 `""` |
| `origin` | 항상 빈 문자열 (고시정보 API 없음) |
| `material` | 항상 빈 문자열 |
| `manufacturer` | 항상 빈 문자열 |
| `color` | 상품명에서 추출해야 함 |
| `careInstructions` | 없음 |
| `qualityGuarantee` | 없음 |
| `options[].stock` | 0 또는 1 (정확한 재고수량 제공 안 됨) |

> KREAM은 리셀 플랫폼이므로 고시정보 체계가 일반 쇼핑몰과 다르다.
> 체크리스트 F1~F6 항목은 대부분 면제 대상이다.

## 알려진 이슈

### 이미지 미수집
- **현상:** 이미지가 빈 배열로 수집됨
- **원인:** __NUXT__ 데이터 로드 타이밍
- **해결:** 현재 방식 유지 (탭 active 전환 후 재시도)

### 옵션 가격 0원
- **현상:** 일부 사이즈의 ask가 0원
- **원인:** 해당 사이즈에 매도 입찰이 없음 (구매입찰만 존재)
- **해결:** ask=0이면 해당 옵션은 isSoldOut=true 처리 (stock=0)
