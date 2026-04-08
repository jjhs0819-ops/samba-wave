# 오토튠 + 확장앱 속도 설정 레지스트리

> 최종 갱신: 2026-04-08

## 오토튠 Refresher 동시성 설정

파일: `backend/backend/domain/samba/collector/refresher.py`

### SITE_CONCURRENCY (동시 요청 수)

| 소싱처 | Cloud Run | Local | 라인 | 비고 |
|--------|-----------|-------|------|------|
| MUSINSA | **40** | 10 | 28 | 가장 높음 (API 기반) |
| FashionPlus | 10 | 3 | 30 | |
| Nike | 5 | 2 | 31 | |
| Adidas | 5 | 2 | 32 | |
| ABCmart | 5 | 2 | 33 | |
| GrandStage | 5 | 2 | 34 | |
| REXMONDE | 5 | 2 | 35 | |
| KREAM | 5 | 2 | 29 | |
| SSG | **3** | **1** | 37 | **가장 보수적** |
| LOTTEON | 5 | 2 | 39 | |
| GSShop | 5 | 2 | 38 | |
| ElandMall | 5 | 2 | 40 | |
| SSF | 5 | 2 | 41 | |
| DANAWA | 5 | 2 | 43 | |
| 기본값 | 10 | 5 | 25 | 미등록 사이트 |

### SITE_BASE_INTERVAL (기본 인터벌, 초)

| 소싱처 | 인터벌 | 라인 | 비고 |
|--------|--------|------|------|
| 대부분 | 1.0초 | 44-54 | 기본값 |
| LOTTEON | **0.5초** | 55 | 다른 사이트의 절반 |
| 기본값 | 1.0초 | 44 | |

### 적응형 인터벌 알고리즘

```
성공 시:
  현재_인터벌 -= INTERVAL_STEP (사이트별 0.2~0.5초)
  최소값: SITE_MIN_INTERVAL (대부분 0초)

실패 시 (429/403/차단):
  현재_인터벌 += 1.0초
  연속 5회 실패 시 최대값까지 증가

DB 저장:
  30초마다 현재 인터벌을 DB에 저장
  서버 재시작 시 복구
```

코드 위치:
- 성공 감소: `refresher.py:608-620`
- 실패 증가: `refresher.py:620-640`
- DB 저장: `refresher.py:375-420`

## 오토튠 가격/재고 동기화

파일: `backend/backend/api/v1/routers/samba/collector_autotune.py`

| 항목 | 설정값 | 라인 | 비고 |
|------|--------|------|------|
| 동시성 (Semaphore) | **2** | 738 | 동시 2개씩 처리 |
| API 429 방지 딜레이 | 0.5초 | 773 | 요청 간 대기 |
| 배치 크기 | 10건 | 776 | 청크 단위 처리 |
| 사이클 대기 | 5초 | 1075 | 갱신 완료 후 다음 사이클 |
| 에러 후 대기 | 2초 | 1109, 1139 | 에러 발생 시 |

### 개선 가능성
- sem 2 → 5: 동시 처리량 2.5배 증가 (API 안정성 테스트 필요)
- 배치 크기 10 → 20: 처리 단위 확대
- 사이클 대기 5초 → 2초: 빈번한 갱신 가능

---

## 확장앱 폴링 설정

파일: `extension/background.js`, `extension-web/background.js`

### 폴링 엔진 (3단계)

| 모드 | 간격 | 조건 | ext 라인 | ext-web 라인 |
|------|------|------|----------|-------------|
| **setInterval (보조)** | **1초** | SW 활성 중 | 895-897 | 866-868 |
| **chrome.alarms (백업)** | 30초 | 항상 (SW 비활성 포함) | 889 | 860 |
| **집중 폴링 (focusPoll)** | **0.5초** | job 발견 시 자동 진입 | 860 | 822 |

### 집중 폴링 상세
- 진입 조건: `runPollCycle()`에서 job 발견 시
- 간격: `await wait(3000)` → 3초
- 최대 횟수: 20회 (약 60초)
- 종료 후: alarm 대기 모드 복귀
- 코드: `runFocusPoll()` (ext:844-864, ext-web:806-826)

### 자동 중지
- `MAX_EMPTY_POLLS = 30` (10초 × 30 = 5분)
- 현재 코드에서 자동중지 주석 처리됨 (항상 폴링)

### 사이트별 탭 대기 시간

| 사이트/작업 | 대기 시간 | ext 라인 | 비고 |
|------------|----------|----------|------|
| 탭 로드 완료 | 최대 30초 | 701-714 | 500ms 간격 체크 |
| active 탭 렌더링 | 5초 | 1394 | category-scan, FashionPlus |
| 비active 탭 렌더링 | 4초 | 1394 | 일반 search |
| GSShop 카테고리 추가 | +3초 | 1399 | JS 렌더링 (총 8초) |
| GSShop 페이지네이션 | 4초 | 1482 | 다음 페이지 렌더링 |
| KREAM Nuxt 하이드레이션 | 3초 | 393 | __NUXT__ 데이터 |
| LOTTEON 혜택가 재시도 | 3초 | 1514 | 렌더링 지연 대비 |
| 쿠키 동기화 | 5분 주기 | 916 | chrome.alarms |

### 4큐 폴링 구조
`runPollCycle()`과 `runFocusPoll()`에서 4개 큐를 **순차 호출**:

```js
// 현재: 순차 (약 400ms)
const hadCollect = await pollCollectOnce()   // kream/collect-queue
const hadSearch = await pollSearchOnce()     // kream/search-queue
const hadSourcing = await pollSourcingOnce() // sourcing/collect-queue
const hadAi = await pollAiSourcingOnce()     // ai-sourcing/collect-queue
```

### 개선 가능성

| 항목 | 현재 | 개선안 | 효과 |
|------|------|--------|------|
| setInterval | 10초 | 1~3초 | 평균 대기 5초→0.5~1.5초 |
| 집중폴링 간격 | 3초 | 0.5~1초 | job 간 대기 단축 |
| 4큐 순차 → 병렬 | ~400ms | ~100ms (Promise.all) | 폴 사이클 75% 단축 |
| waitForTabLoad | 500ms 폴링 | 이벤트 구동 | 즉시 감지 |
| GSShop 고정 대기 8초 | 고정 sleep | 동적 DOM 감지 | 평균 2~3초 |
| GSShop 페이지네이션 4초 | 고정 sleep | 동적 DOM 감지 | 평균 1.5초 |
| alarm | 30초 | 30초 (Chrome 하한) | 변경 불가 |

---

## Chrome MV3 제약사항

- **Service Worker 자동 종료**: idle ~30초 후 Chrome이 SW 종료
- **alarm 최소 주기**: 30초 (`periodInMinutes: 0.5`가 최소)
- **setInterval**: SW 활성 중만 동작. SW 종료 시 함께 중단
- **keepalive 없음**: 현재 persistent port (onConnect) 미사용
- **WebSocket/SSE**: 미사용. SW에서 지원하나 종료 시 연결 끊김
