# 더현대Hi 소싱처 개발 핸드오프 (2026-07-13 재작성)

> ⚠️ 원본 핸드오프 문서는 claude.ai 웹 세션(session_015xUKd3hA5LxTsJhDpwqSCR)
> 샌드박스에서 유실됨. 이 문서는 커밋 932ef546b + 현 인프라 기준으로 재구성한 버전.
> 원본이 전제한 "VM 운영 + 맥미니 로컬" 구도는 폐기 — 현재는 윈도우PC 로컬 운영.

## 현재 상태 (2026-07-13)

| 항목 | 상태 |
|---|---|
| 플러그인 본체 | ✅ `feat/thehyundai-local` 브랜치 커밋 `bbd1cb8a6` (932ef546b cherry-pick + Referer 대응) |
| 구현 범위 | search / get_detail / refresh(오토튠) / scan_categories / discover_brands 5종 전부 |
| 단위테스트 | ✅ 62/62 PASSED |
| 라이브 검증 | ✅ 2026-07-13 실측: search 36건, detail 옵션2·이미지6, brands 319, categories 1,362, refresh 전 필드 정상 |
| 계정등록·송장수집 | ✅ 이미 origin main 병합됨 (750364225, 242fd5eb6, 78e8eeddd) |
| 프론트 | 수집 드롭다운 `THEHYUNDAI` 항목 존재하나 `disabled: true` |
| 배포 | ⏳ 미배포 — 윈도우PC 컨테이너 env + 이미지 갱신 필요 |

## 옵션A = env var gate (구 "LOCAL_THEHYUNDAI_MODE")

플래그 실명은 **`ENABLE_THEHYUNDAI=1`** (커밋 932ef546b에서 이미 구현·테스트됨 —
rename 불필요). 미설정 시 플러그인 클래스가 모듈에서 제거돼 discover_plugins 가
못 찾음 → 모든 코드 경로 자연 차단.

### 구 계획 → 현 상황 보정

| 구 계획 전제 (VM+맥미니, ~06월) | 현 상황 (윈도우PC 로컬, 06-27 이사 후) |
|---|---|
| 운영=GCP VM, 더현대는 맥미니 로컬에서만 | 운영 백엔드 자체가 로컬 윈도우PC(주거용 IP) |
| 플래그로 운영/로컬 코드 경로 분리 필수 | 분리 불필요 — **운영 컨테이너에 `ENABLE_THEHYUNDAI=1` 직접 설정**하면 끝 |
| VM 데이터센터 IP 차단 우려 | 해소 — 공인 IP 182.215.150.82 (주거용) |
| VM 2코어 부하 우려 | 해소 — Ryzen7 8코어, 오토튠 동시성 28 재분배 완료. 플러그인 concurrency=3, 사이클당 2~3 hop 경량 |

플래그는 "로컬 전용 격리" 용도에서 **"켜기 전 안전 스위치"** 용도로 의미가 바뀜.
게이트 자체는 그대로 유지 (문제 시 env 제거+재기동만으로 완전 차단 가능).

## 2026-07 사이트 변경 (실측)

- `/proxy/*` GET 이 **Referer 헤더 미포함 시 HTTP 500** (6월엔 익명 200).
  값은 아무 URL이나 통과 — `_client()` 기본 헤더로 대응 완료.
- 검색 페이지 경로 `/search/result?searchQuery=` → `/search?q=&tab=product` 로 변경
  (API 경로 `/proxy/v1/dp/search/searchResult` 는 불변, 파라미터도 불변).
- 응답 envelope(`{result, messageCode, data}`)·파싱 로직 불변.

## 남은 작업 (순서대로)

1. **origin 최신 동기화 확인 후 main 계열 병합** — `feat/thehyundai-local` → 배포 브랜치.
2. **윈도우PC 배포** — 이미지 재빌드(amd64) → `save|ssh load` → compose에
   `ENABLE_THEHYUNDAI=1` 추가 → `--force-recreate`. (절차: 메모리 `windows-deploy-procedure`)
3. **프론트 드롭다운 활성화** — `frontend/src/app/samba/collector/constants.ts`
   `THEHYUNDAI` 의 `disabled: true` 제거 → myfork push → Vercel.
4. **소싱 계정 등록** — `/accounts` 에서 더현대 계정 (id "TheHyundai", 정규화가
   THEHYUNDAI로 수렴). 단 전 API 익명 200이라 수집엔 계정 불요, 주문용.
5. **첫 수집 파일럿** — 브랜드 단위(예: 더현대-나이키) 소량 수집 → 가공 → 카테고리
   매핑 확인 → 마켓 전송은 보고→확인 후.
6. **오토튠 편입** — 매핑 생성 시 자동 사이클 진입 (`_get_active_sites_cached` 가
   source_site 자동 enumerate). 시작/중지는 사장님 직접.

## 함정 메모

- `searchType=NCP_PRODUCT` 미지정 시 productList 미반환 (트랩, 코드 반영됨).
- 다차원 옵션: `uitmCombYn=="1"` 이면 uitmStckList 필수 (코드 반영됨).
- `bnftReCalcList` 서버 500 버그 → uitmDcPrc 폴백 (코드 반영됨).
- new_cost = aplyDcPrc − Σstep8a − Σstep8b (카드즉시할인 반영, SSG 선례).
- 소싱처 우선순위: 무신사 > ABC > 롯데온 > 패플 > SSG > GS > **더현대** (최하위).
