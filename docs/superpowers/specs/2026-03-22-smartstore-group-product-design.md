# 스마트스토어 그룹상품 완전자동화 설계

## 1. 개요

수집된 상품 중 같은 모델의 다른 색상 변형을 자동 감지하여,
스마트스토어 그룹상품 API(`POST /v2/standard-group-products`)로 묶어 등록하는 기능.

### 목표
- 수집 시 자동 그룹핑 키 생성 (D방식: similarNo → styleCode 모델코드 → 상품명 패턴)
- 전송 시 그룹 미리보기 모달 → 확인 후 그룹상품 등록
- 기존 단일등록 상품은 삭제 후 그룹으로 재등록
- 카테고리 미지원 시 기존 단일상품 방식 폴백

## 2. 데이터 모델 변경

### SambaCollectedProduct 신규 필드

| 필드 | 타입 | 설명 |
|------|------|------|
| `group_key` | `String(255)` | 그룹핑 키 (같은 값 = 같은 그룹) |
| `similar_no` | `String(50)` | 무신사 similarNo (수집 시 저장) |
| `color` | `String(100)` | 색상 (상품명에서 파싱) — **이미 모델에 존재**, 미사용 시 활용 |
| `group_product_no` | `BigInteger` | 스마트스토어 그룹상품번호 (등록 후 저장) |

> **참고**: `color` 필드는 기존 모델에 이미 존재하므로 마이그레이션 불필요. 실제 추가 컬럼은 3개.

### group_key 생성 규칙 (우선순위)

1. `similarNo`가 0이 아닌 경우 → `"similar_{similarNo}"`
2. `style_code`에서 하이픈 앞 모델코드 추출 → `"style_{brand}_{modelCode}"`
   - 예: `CW2288-111` → `"style_nike_CW2288"`
3. 상품명 ` - ` 앞부분 패턴 → `"name_{brand}_{modelName}"`
   - 예: `"에어 포스 1 07 M - 화이트"` → `"name_nike_에어 포스 1 07 M"`

**제약사항:**
- 같은 `search_filter_id`(검색그룹) 내에서만 그룹핑
- `group_key`가 같아도 다른 검색그룹이면 별도 처리

## 3. 수집 단계 변경

### 3.1 무신사 수집기 변경 (collector.py)

**추가 수집 데이터:**
- 상세 API에서 `similarNo` 필드 추가 수집 → `similar_no`에 저장
- 상품명 파싱으로 `color` 추출:
  ```
  "에어 포스 1 07 M - 화이트 / CW2288-111"
                      ^^^^^^ color = "화이트"
  ```
- 파싱 규칙: ` - ` 와 ` / ` 사이의 텍스트가 색상

**group_key 생성 시점:**
- 상품 저장 시 D방식 우선순위로 자동 생성
- 기존 상품 갱신(refresh) 시에도 group_key가 없으면 재생성

### 3.2 색상 파싱 로직

```python
def parse_color_from_name(name: str) -> str:
    """상품명에서 색상 추출. ' - '와 ' / ' 사이 텍스트."""
    if ' - ' in name:
        after_dash = name.split(' - ', 1)[1]
        if ' / ' in after_dash:
            return after_dash.split(' / ', 1)[0].strip()
        return after_dash.strip()
    return ""
```

### 3.3 group_key 생성 로직

```python
def generate_group_key(product: dict) -> str | None:
    """D방식 그룹핑 키 생성."""
    brand = (product.get("brand") or "").lower().replace(" ", "_")

    # 1순위: similarNo
    similar_no = product.get("similar_no") or "0"
    if similar_no != "0":
        return f"similar_{similar_no}"

    # 2순위: style_code 모델코드
    style_code = product.get("style_code") or ""
    if "-" in style_code:
        model_code = style_code.rsplit("-", 1)[0]
        if model_code and brand:
            return f"style_{brand}_{model_code}"

    # 3순위: 상품명 패턴
    name = product.get("name") or ""
    if " - " in name:
        model_name = name.split(" - ", 1)[0].strip()
        if model_name and brand:
            return f"name_{brand}_{model_name}"

    return None  # 그룹핑 불가
```

## 4. 전송 단계 변경

### 4.1 전송 플로우

```
전송 버튼 클릭
  ↓
백엔드: 전송 대상 상품에서 group_key별 그룹 감지
  ↓
프론트: 미리보기 모달 표시
  ├ 그룹상품 목록 (2건 이상 묶인 것)
  ├ 단일상품 목록 (그룹핑 안 된 것)
  └ 기존 삭제 대상 안내
  ↓
사용자 확인 → 전송 시작
  ↓
[그룹상품 처리]
  ├ 카테고리 그룹상품 지원 여부 확인 (guideId 조회)
  │  ├ 지원 → 그룹상품 등록
  │  └ 미지원 → 기존 단일상품 방식 폴백
  ├ 기존 단일등록 상품 삭제 (originProductNo 있는 경우)
  ├ POST /v2/standard-group-products 호출
  ├ 폴링 (GET /v2/standard-group-products/status, 최대 5분)
  └ groupProductNo + productNos 저장
  ↓
[단일상품 처리]
  └ 기존 방식 그대로 (POST /v2/products)
```

### 4.2 미리보기 API

**엔드포인트:** `POST /samba/shipment/group-preview`

**요청:**
```json
{
  "product_ids": ["id1", "id2", ...],
  "account_id": "smartstore_account_1"
}
```

**응답:**
```json
{
  "groups": [
    {
      "group_key": "style_nike_CW2288",
      "group_name": "에어 포스 1 07 M",
      "products": [
        {
          "id": "prod_1",
          "name": "에어 포스 1 07 M - 화이트 / CW2288-111",
          "color": "화이트",
          "sale_price": 149000,
          "thumbnail": "https://...",
          "existing_product_no": "10000001"  // 기존 등록 있으면
        },
        {
          "id": "prod_2",
          "name": "에어 포스 1 07 M - 블랙 / CW2288-001",
          "color": "블랙",
          "sale_price": 149000,
          "thumbnail": "https://...",
          "existing_product_no": null
        }
      ]
    }
  ],
  "singles": [
    {
      "id": "prod_5",
      "name": "보메로 플러스",
      "sale_price": 189000
    }
  ],
  "delete_count": 1,
  "group_count": 2,
  "single_count": 1
}
```

### 4.3 그룹상품 전송 API

**엔드포인트:** `POST /samba/shipment/group-send`

**요청:**
```json
{
  "groups": [
    {
      "group_key": "style_nike_CW2288",
      "product_ids": ["prod_1", "prod_2"]
    }
  ],
  "singles": ["prod_5"],
  "account_id": "smartstore_account_1"
}
```

## 5. 스마트스토어 API 연동

### 5.1 신규 메서드 (SmartStoreClient)

```python
class SmartStoreClient:
    # 기존 메서드 유지 + 아래 추가

    async def get_purchase_option_guides(self, category_id: str) -> list:
        """카테고리별 판매옵션 가이드 조회"""
        # GET /v2/standard-purchase-option-guides?categoryId={id}

    async def register_group_product(self, payload: dict) -> dict:
        """그룹상품 등록 (비동기)"""
        # POST /v2/standard-group-products

    async def poll_group_status(self, max_wait=300) -> dict:
        """그룹상품 등록 상태 폴링 (최대 5분)"""
        # GET /v2/standard-group-products/status

    async def update_group_product(self, group_no: int, payload: dict) -> dict:
        """그룹상품 수정"""
        # PUT /v2/standard-group-products/{groupProductNo}

    async def delete_group_product(self, group_no: int) -> dict:
        """그룹상품 삭제"""
        # DELETE /v2/standard-group-products/{groupProductNo}

    def transform_group_product(self, products: list, account_settings: dict) -> dict:
        """수집된 상품 리스트 → 그룹상품 API 페이로드 변환"""
```

### 5.2 transform_group_product 변환 규칙

**공통(groupProduct) 레벨:**
- `leafCategoryId`: 첫 번째 상품의 카테고리 (전체 동일해야 함)
- `name`: group_key에서 추출한 모델명 또는 첫 상품명에서 색상 제거한 이름
- `guideId`: 카테고리별 조회 결과에서 선택
- `brandName`, `brandId`: 공통 브랜드
- `afterServiceInfo`: 계정 설정에서
- `productInfoProvidedNotice`: 첫 상품 기준
- `commonDetailContent`: 공통 상세 HTML

**개별(specificProducts) 레벨:**
- `standardPurchaseOptions`: guideId에 맞는 옵션 (색상 = color 필드)
- `salePrice`: 각 상품별 정책 적용 가격
- `stockQuantity`: 각 상품별 재고
- `images`: 각 상품별 이미지
- `deliveryInfo`: 계정 설정 기반
- `sellerCodeInfo.sellerManagementCode`: style_code
- `smartstoreChannelProduct`: 채널 설정

### 5.3 비동기 폴링 로직

```python
async def poll_group_status(self, max_wait=300):
    """그룹상품 등록 결과 폴링. 최대 5분."""
    start = time.time()
    while time.time() - start < max_wait:
        result = await self._get("/v2/standard-group-products/status")
        state = result.get("progress", {}).get("state")
        if state == "COMPLETED":
            return result
        elif state in ("ERROR", "FAILED"):
            raise Exception(f"그룹상품 등록 실패: {result}")
        await asyncio.sleep(3)  # 3초 간격 폴링
    raise TimeoutError("그룹상품 등록 타임아웃 (5분 초과)")
```

## 6. 프론트엔드 변경

### 6.1 상품관리 페이지 (products/page.tsx)
- 그룹 배지 표시: `group_key`가 있는 상품에 색상 태그 표시
- 같은 group_key 상품끼리 시각적으로 구분

### 6.2 수집 페이지 (collector/page.tsx)
- 전송 버튼 클릭 시 → 그룹 미리보기 모달
- 모달 구성:
  - 그룹상품 섹션: 그룹별로 묶인 상품 리스트 (썸네일+색상+가격)
  - 단일상품 섹션: 그룹핑 안 된 상품
  - 기존 삭제 안내: "기존 단일등록 N건 삭제 후 그룹으로 재등록"
  - [취소] [전송] 버튼

### 6.3 API 클라이언트 (api.ts)
```typescript
// 그룹 미리보기
groupPreview: (productIds: string[], accountId: string) =>
  request<GroupPreviewResponse>(`${SAMBA_PREFIX}/shipments/group-preview`, {
    method: 'POST',
    body: JSON.stringify({ product_ids: productIds, account_id: accountId }),
  }),

// 그룹 전송
groupSend: (groups: GroupSendRequest) =>
  request<GroupSendResponse>(`${SAMBA_PREFIX}/shipments/group-send`, {
    method: 'POST',
    body: JSON.stringify(groups),
  }),
```

## 7. 수정 대상 파일

| 파일 | 변경 내용 |
|------|----------|
| `backend/domain/samba/collector/model.py` | `group_key`, `similar_no`, `color`, `group_product_no` 필드 추가 |
| `backend/api/v1/routers/samba/collector.py` | 수집 시 group_key 생성, 색상 파싱 |
| `backend/domain/samba/proxy/smartstore.py` | `transform_group_product()`, guideId 조회, 그룹 등록/수정/삭제/폴링 |
| `backend/domain/samba/shipment/dispatcher.py` | `_handle_smartstore_group()` 핸들러 |
| `backend/domain/samba/shipment/service.py` | 그룹 감지, 미리보기 데이터 생성, 기존 삭제 로직 |
| `backend/api/v1/routers/samba/shipment.py` | group-preview, group-send 엔드포인트 |
| `frontend/src/lib/samba/api.ts` | groupPreview, groupSend API |
| `frontend/src/app/samba/collector/page.tsx` | 그룹 미리보기 모달 |
| `frontend/src/app/samba/products/page.tsx` | 그룹 배지 |
| alembic 마이그레이션 | 3개 컬럼 추가 (group_key, similar_no, group_product_no) |

## 8. 엣지 케이스 처리

| 케이스 | 처리 |
|--------|------|
| 그룹 내 상품 카테고리가 다름 | 첫 상품 카테고리 기준, 경고 표시 |
| 카테고리가 그룹상품 미지원 | 기존 단일상품 방식으로 폴백 |
| 그룹 내 상품이 1건뿐 | 단일상품으로 전송 |
| 스토어당 1건 동시 처리 제한 | 큐 순차 처리, 이전 요청 완료 대기 |
| 폴링 5분 타임아웃 | 에러 반환, 수동 확인 안내 |
| 기존 상품 삭제 실패 | 삭제 실패 상품 스킵, 나머지 진행 |
| 삭제 성공 후 그룹 등록 실패 | 단일상품으로 재등록(롤백) |
| 그룹 내 가격이 서로 다름 | 허용 — specificProduct마다 개별 salePrice |
| 이미지 업로드 | 그룹 내 각 상품별 이미지를 개별 업로드 후 URL 치환 |
| 동시 그룹 등록 요청 | account_id별 in-memory 락으로 순차 처리 |

## 9. API 경로 규칙

기존 shipment 라우터 prefix(`/shipments`)에 맞춰:
- `POST /samba/shipments/group-preview`
- `POST /samba/shipments/group-send`
| guideId에 맞는 옵션이 없음 | 단일상품 폴백 |
