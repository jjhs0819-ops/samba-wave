# SSG 배치 수집 설계

**날짜:** 2026-04-06  
**상태:** 승인됨

---

## 배경

SSG.COM은 robots.txt가 엄격하고 단시간 다량 요청 시 429/403으로 수집을 차단한다.  
현재 SSG 수집은 최대 100개 고정이며, 재수집 시 Job Worker에서 "미지원 소싱처" 오류가 발생하는 버그가 있다.

## 목표

- 사용자는 기존대로 `요청수`만 입력 (UI 변경 없음)
- 시스템이 내부에서 **50개 단위로 분할**, 배치 간 **60초 대기**하여 SSG 차단 회피
- `requested_count`를 정확히 반영하여 500개 요청 시 실제 500개 수집

## 버그 수정 포함

SSG 재수집 시 Job Worker → `_collect_direct_api` → SITE_SEARCH_URLS 미등록으로 실패하는 문제를 함께 수정.

---

## 구현 설계

### 변경 파일

**`backend/backend/domain/samba/job/worker.py`만 수정** (다른 파일 변경 없음)

### 1. 라우팅 추가 (`_collect_job`)

```python
# 기존 routing 위에 SSG 전용 분기 추가
if site == "SSG":
    await self._collect_ssg(job, sf, session, repo)
    return
```

### 2. `_collect_ssg` 메서드 신규 추가

```
SSG_BATCH_SIZE = 50   # 배치당 수집 개수
SSG_BATCH_DELAY = 60  # 배치 간 대기 (초)
SSG_PAGE_SIZE = 40    # SSG API 한 페이지 크기
```

**흐름:**

```
1. requested_count - existing_count = remaining 계산
2. SSGSourcingClient.search_products() 로 후보 상품 수집 (페이지네이션)
3. 중복 필터링 (DB에 이미 있는 site_product_id 제외)
4. 배치 루프:
   for i, item_id in enumerate(targets):
       if i > 0 and i % SSG_BATCH_SIZE == 0:
           log("배치 N/M 완료, 60초 대기 중...")
           sleep(SSG_BATCH_DELAY)
       SSGSourcingClient.get_product_detail(item_id)
       → svc.create_collected_product(product_data)
       sleep(1.0)  # 상품별 딜레이
5. complete_job() 호출
```

### 3. 상품 데이터 빌드

기존 `collector_collection.py`의 SSG 수집 로직과 동일한 `_build_product_data()` 헬퍼 재사용.

---

## 수집 시간 예측

| 요청 수 | 배치 수 | 예상 소요 시간 |
|--------|--------|--------------|
| 100개  | 2배치  | ~2분 + 60초 대기 |
| 300개  | 6배치  | ~6분 + 300초 대기 |
| 500개  | 10배치 | ~10분 + 540초 대기 |

---

## 로그 예시

```
[SSG] 배치 1/10 완료, 60초 대기 중... (50/500)
[SSG] 배치 2/10 완료, 60초 대기 중... (100/500)
...
[SSG] 수집 완료: 500개 저장
```

---

## 영향 범위

- SSG 소싱처 수집에만 적용
- 무신사, 패션플러스, 나이키 등 다른 소싱처 동작에 영향 없음
- UI 변경 없음
