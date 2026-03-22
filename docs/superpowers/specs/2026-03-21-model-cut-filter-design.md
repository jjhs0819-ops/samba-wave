# 상품 이미지 자동 필터링 설계

## 개요

수집된 상품 이미지에서 순수 이미지컷만 추출하는 기능.
단색/단순 배경에 상품만 촬영된 이미지만 남기고, 모델컷·연출컷·배너·사이즈표 등 나머지는 모두 제거한다.
이미지컷이 존재하면 나머지를 삭제하고, 이미지컷이 하나도 없으면 AI로 변환한다.

## 분류 기준

**보존 (이미지컷)**:
- 단색/단순 배경에 상품만 단독 촬영된 사진
- 행거컷, 평놓기, 마네킹 촬영
- 상품 각도별 촬영 (정면, 측면, 후면, 밑창 등)
- 상품 디테일 클로즈업

**삭제 대상**:
- 모델컷 (사람이 착용/포즈)
- 연출컷 (야외, 소품, 라이프스타일 배경)
- 브랜드 배너, 로고 이미지
- 사이즈표, 스펙표
- 기타 마케팅 이미지

**예외**: 상품 자체에 사람이 프린팅된 경우는 이미지컷으로 분류

## 처리 범위

- **`images` 필드**: 모델컷 분류 및 필터링 대상
- **`detail_images` 필드**: 처리하지 않음 (상세 페이지 이미지는 마켓 등록 시 HTML로 조합되므로 별도 관리)
- **대표 이미지**: `images[0]`이 대표 이미지 역할. 필터링 후 `images`가 비지 않는 한 자연스럽게 `images[0]`이 새 대표 이미지가 됨

## 핵심 흐름

```
사용자 트리거 (단일/다중/그룹)
    ↓
이미지 다운로드 (바이트) + base64 인코딩
    ↓
Claude Vision API로 분류 (최대 20장을 1회 요청에 묶어 전송)
    ↓
각 이미지를 "이미지컷" / "기타" 분류
    ↓
[이미지컷 존재] → 기타 전부 삭제, 이미지컷만 보존
[이미지컷 없음] → Fireworks AI 배경제거 모드로 변환 → 이미지컷으로 교체
    ↓
DB 업데이트 (images 필드, 상품 단위 커밋)
```

## 백엔드 설계

### 새 서비스: `backend/domain/samba/image/image_filter_service.py`

**주요 메서드:**

| 메서드 | 역할 |
|--------|------|
| `_download_and_encode(url: str) -> tuple[str, str]` | 이미지 다운로드 후 base64 인코딩. 반환: `(base64_data, media_type)` |
| `classify_images(urls: list[str]) -> list[dict]` | 최대 20장을 1회 Claude 요청에 묶어 분류. 반환: `[{"url": ..., "type": "product"/"other"}]` |
| `filter_product(product_id: str) -> dict` | 단일 상품 이미지 필터링 |
| `batch_filter(product_ids: list[str]) -> dict` | 다중 상품 일괄 필터링 |
| `filter_by_group(filter_id: str) -> dict` | 수집 그룹(search_filter_id) 단위 필터링 |

### Claude Vision 판별 로직

**이미지 전달 방식**: CDN URL을 직접 전달하면 Referer/Cookie 인증 문제로 403이 발생할 수 있다.
기존 `ImageTransformService._download_image` 패턴을 따라 이미지를 바이트로 다운로드한 후 base64로 인코딩하여 Claude에 전달한다.

**배치 전략**: 이미지를 최대 20장씩 묶어 1회 Claude 요청에 전송한다.
- 상품당 평균 5-8장이므로 대부분 1회 요청으로 처리
- API Rate Limit 부담 최소화 + 비용 절감

**프롬프트 설계:**
```
아래 상품 이미지들을 각각 분류하세요:

- "product": 단색 또는 단순 배경에 상품만 단독 촬영된 사진
  (행거컷, 평놓기, 마네킹, 각도별 촬영, 디테일 클로즈업, 밑창 등)
- "other": 그 외 모든 이미지
  (모델 착용, 연출/라이프스타일, 야외 배경, 브랜드 배너, 사이즈표, 스펙표, 로고 등)

주의:
- 상품 자체에 사람이 프린팅된 경우는 "product"로 분류
- 배경이 단색(흰색, 회색, 검정 등)이고 상품만 있으면 "product"
- 배경에 소품, 자연환경, 실내 인테리어 등이 보이면 "other"

이미지 순서대로 JSON 배열로 답변:
[{"index": 0, "type": "product"}, {"index": 1, "type": "other"}, ...]
```

**비용 추정:**
- Claude Sonnet Vision: 이미지 20장 묶음당 ~$0.02-0.05
- 상품당 평균 5-8장 → 상품당 1회 요청 ~$0.01-0.03
- 배치 100상품 → ~$1.0-3.0

### 처리 분기 로직

```python
async def filter_product(self, product_id: str) -> dict:
    product = await self.product_repo.get_async(product_id)
    images = product.images or []
    if not images:
        return {"action": "skipped", "reason": "no_images"}

    # 1. 이미지 분류 (최대 20장 묶음 전송)
    classifications = await self.classify_images(images)
    product_cuts = [c["url"] for c in classifications if c["type"] == "product"]
    others = [c["url"] for c in classifications if c["type"] == "other"]

    # 2. 분기 처리
    if product_cuts:
        # 이미지컷 존재 → 나머지 전부 삭제
        await self.product_repo.update_async(product_id, images=product_cuts)
        return {"action": "filtered", "removed": len(others), "kept": len(product_cuts)}
    else:
        # 이미지컷 없음 → Fireworks AI로 변환
        transformed = await self.transform_to_product_cuts(others)
        await self.product_repo.update_async(product_id, images=transformed)
        return {"action": "transformed", "count": len(transformed)}
```

### 트랜잭션 전략

**상품 단위 커밋 (부분 성공 허용)**:
- `batch_filter`에서 상품마다 개별 커밋 (`update_async` 내부 commit)
- 중간에 실패해도 이미 처리된 상품은 유지
- 실패한 상품은 `errors` dict에 기록하여 응답에 포함
- 재시도 시 이미 처리된 상품은 건너뜀 (이미지가 이미 필터링됨)

### Fireworks AI 변환 (모델컷 → 이미지컷)

기존 `ImageTransformService`의 `background` 모드를 활용한다.
- 모델+배경 제거 → 상품만 남김
- 변환된 이미지를 R2/로컬에 저장
- 저장된 URL로 `images` 필드 교체

### API 엔드포인트

**라우터**: `backend/api/v1/routers/samba/proxy.py`에 추가

```
POST /api/v1/samba/proxy/model-cut/filter
```

**요청:**
```json
{
  "product_ids": ["cp_xxx", "cp_yyy"],
  "filter_id": "sf_xxx"
}
```
- `product_ids`: 단일/다중 상품 ID 리스트 (우선)
- `filter_id`: 수집 그룹 ID (`search_filter_id` 기반, `product_ids`가 비어있을 때만 사용)

**우선순위**: `product_ids`가 있으면 `filter_id` 무시. 기존 `/fireworks/transform` 엔드포인트와 동일한 패턴.

**응답:**
```json
{
  "success": true,
  "results": {
    "cp_xxx": {"action": "deleted", "removed": 3, "kept": 5},
    "cp_yyy": {"action": "transformed", "count": 4}
  },
  "total": 2,
  "errors": {}
}
```

### 에러 처리

- 이미지 다운로드 실패 → 해당 이미지를 "product"로 분류 (원본 유지)
- Claude Vision API 실패 → 해당 상품 건너뜀, errors에 기록
- Fireworks 변환 실패 → 원본 모델컷 유지, errors에 기록
- 이미지가 0장인 상품 → 건너뜀 (action: "skipped")

## 프론트엔드 설계

### 트리거 위치 (3곳)

**1. 상품 목록 (collector/page.tsx)**
- 체크박스 선택 후 상단 액션 바에 "이미지 필터링" 버튼 추가
- 선택 없이 전체 필터링 불가 (명시적 선택 필요)

**2. 상품 상세 (개별 상품 카드/모달)**
- 상품 이미지 영역에 "이미지 필터링" 버튼

**3. 수집 그룹 (수집 작업 목록)**
- 수집 그룹 행에 "이미지 필터링" 버튼
- 해당 그룹에 속한 전체 상품 일괄 처리 (`filter_id` 파라미터 사용)

### 진행 상태 표시

- 처리 시작: 버튼 비활성화 + "처리중..." 텍스트
- 처리 완료: 토스트 알림 "이미지 필터링 완료 — N개 삭제, M개 변환"
- 부분 실패: 토스트 알림 "N개 완료, M개 실패"

### API 호출

`frontend/src/lib/samba/api.ts`에 추가:

```typescript
filterProductImages(productIds: string[], filterId?: string): Promise<ImageFilterResult>
```

## 파일 변경 목록

### 새 파일
- `backend/domain/samba/image/image_filter_service.py` — 이미지 분류/필터링 서비스

### 수정 파일
- `backend/api/v1/routers/samba/proxy.py` — API 엔드포인트 추가
- `frontend/src/lib/samba/api.ts` — API 함수 추가
- `frontend/src/app/samba/collector/page.tsx` — 버튼 추가 (목록/그룹)

## 제약사항

- Claude Vision API 비용 발생 (배치 100상품 기준 ~$1-3)
- Fireworks AI 변환 비용 발생 (배경제거 이미지당)
- 대량 처리 시 시간 소요 (상품당 2-5초)
- 변환 품질은 Fireworks 배경제거 성능에 의존
