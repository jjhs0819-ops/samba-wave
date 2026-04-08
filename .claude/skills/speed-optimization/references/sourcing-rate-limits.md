# 소싱처별 속도 제한 레지스트리

> 최종 갱신: 2026-04-08

## 속도 제한 종합 표

| 소싱처 | 제한 유형 | 현재값 | 코드 위치 | 비고 |
|--------|---------|-------|----------|------|
| 무신사 | sem(refresher) | Cloud 40 / Local 10 | refresher.py:28 | 가장 높은 동시성 |
| 무신사 | interval(refresher) | 1.0초 | refresher.py:44 | 기본 인터벌 |
| KREAM | sem(refresher) | Cloud 5 / Local 2 | refresher.py:29 | |
| KREAM | interval(refresher) | 1.0초 | refresher.py:45 | |
| ABCmart | delay(검색반복) | 0.3초 | abcmart.py:1367 | 차단 방지 |
| ABCmart | delay(재시도) | 0.5초 | abcmart.py:1412 | null 응답 시 1회 재시도 |
| ABCmart | sem(refresher) | Cloud 5 / Local 2 | refresher.py:33 | |
| ABCmart | 429/403 감지 | RateLimitError | abcmart.py:226 | retry_after 헤더 확인 |
| GrandStage | sem(refresher) | Cloud 5 / Local 2 | refresher.py:34 | ABCmart와 동일 그룹 |
| REXMONDE | sem(refresher) | Cloud 5 / Local 2 | refresher.py:35 | ABCmart와 동일 그룹 |
| GS샵 | sem(카테고리스캔) | **50** | gsshop_sourcing.py:389 | 15→50 증가 (2026-04-08) |
| GS샵 | 429/403 감지 | RateLimitError | gsshop_sourcing.py:32-38 | |
| GS샵 | sem(refresher) | Cloud 5 / Local 2 | refresher.py:38 | |
| GS샵 | 검색 URL 차단 | HTTP 405 | gsshop_sourcing.py:11-12 | 서버단 차단 → 확장앱 큐 위임 |
| 롯데ON | sem(PBF 조회) | 5 | lotteon_sourcing.py:1193 | 판매기록 조회 동시성 |
| 롯데ON | sem(refresher) | Cloud 5 / Local 2 | refresher.py:39 | |
| 롯데ON | 429/403 감지 | RateLimitError | lotteon_sourcing.py:156-162 | |
| SSG | 429/403 감지 | RateLimitError | ssg_sourcing.py:115-118 | robots.txt 엄격 |
| SSG | sem(refresher) | Cloud **3** / Local **1** | refresher.py:37 | **가장 보수적** |
| SSG | interval(refresher) | 1.0초 | refresher.py:53 | |
| 나이키 | delay(페이지간) | 0.2초 | nike.py:315 | |
| 나이키 | sem(refresher) | Cloud 5 / Local 2 | refresher.py:31 | |
| 패션플러스 | 직접 제한 없음 | - | - | 검색API + 상세HTML 파싱 |
| 패션플러스 | sem(refresher) | Cloud 10 / Local 3 | refresher.py:30 | |
| 이랜드몰 | 직접 제한 없음 | - | - | |
| 이랜드몰 | sem(refresher) | Cloud 5 / Local 2 | refresher.py:40 | |
| SSF | 직접 제한 없음 | - | - | |
| SSF | sem(refresher) | Cloud 5 / Local 2 | refresher.py:41 | |
| Cafe24 | 429→2초 재시도 | 2초 | cafe24.py:141-143 | Rate 헤더 모니터링 |
| DANAWA | sem(refresher) | Cloud 5 / Local 2 | refresher.py:43 | |
| Adidas | sem(refresher) | Cloud 5 / Local 2 | refresher.py:32 | |

## 소싱처 분류

### 확장앱 필수 사이트 (JS 렌더링 or 서버 차단)
서버에서 직접 HTTP 요청이 불가능하거나 JS 렌더링이 필요한 사이트.
확장앱 SourcingQueue를 통해 브라우저 탭에서 DOM 파싱.

- **GS샵**: 검색 URL HTTP 405 차단 → 확장앱 큐 위임
- **ABCmart/GrandStage**: 확장앱 큐 지원
- **REXMONDE**: 확장앱 큐 지원
- **롯데ON**: 혜택가 수집 시 확장앱 필요 (pbf API or DOM)
- **이랜드몰**: 확장앱 큐 지원
- **SSF**: 확장앱 큐 지원
- **패션플러스**: SPA 상세 (active 탭 필수)

### 서버 직접 수집 가능 사이트
- **무신사**: API 기반 (네이버 검색 API)
- **KREAM**: Nuxt __NUXT__ 데이터 추출 (확장앱 CDP)
- **SSG**: HTTP 직접 (robots.txt 주의)
- **나이키**: HTTP 직접

## 차단 감지 패턴

모든 소싱처에서 공통으로 사용하는 차단 감지:

```python
# 공통 패턴 (proxy/ 내 각 *_sourcing.py)
if resp.status_code in (429, 403):
    raise RateLimitError(f"{site} rate limit: {resp.status_code}")
```

### 사이트별 특이사항
- **SSG**: robots.txt 엄격, 보수적 간격(2초+) 권장
- **ABCmart**: retry_after 헤더 확인 후 대기
- **GS샵**: 검색은 아예 서버단 차단(405), 상세만 서버 직접 가능
- **롯데ON**: 혜택가 수집 시 쿠키 필수 (pbf API)

## 개선 가능성 메모

| 소싱처 | 현재 | 개선안 | 위험도 |
|--------|------|--------|--------|
| GS샵 카테고리스캔 | sem 50 (적용완료) | sem 100 | 중 (Cloud Run 메모리 주의) |
| SSG | sem 3 | sem 5 | 높 (차단 이력 있음) |
| ABCmart delay | 0.3초 | 0.1초 | 중 |
| 무신사 sem | 40 | 60 | 낮 (API 기반) |
