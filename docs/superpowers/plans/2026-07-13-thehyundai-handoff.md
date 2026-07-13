# 더현대Hi 소싱처 개발 핸드오프 (2026-07-13, 현 인프라 보정판)

> 원본(myfork `claude/sourcing-site-analysis-Ul4YY` 커밋 `316dfe5fe`, 205줄)은
> **VM 운영 + Cloud SQL 공유 + 맥미니 로컬 백엔드** 전제로 작성됨.
> 2026-06-27 윈도우PC 로컬 이사로 전제가 바뀌어 이 보정판으로 대체.
> 원본 전문은 `git show 316dfe5fe:docs/superpowers/plans/2026-07-13-thehyundai-handoff.md`.

## 1. 현재 상태 (2026-07-13)

| 항목 | 상태 |
|---|---|
| 플러그인 본체 | ✅ `feat/thehyundai-local` 브랜치 `bbd1cb8a6` — 원본 `932ef546b` cherry-pick (현재 main 계열 기준, 충돌 2건 해소) |
| 구현 범위 | search / get_detail / refresh(오토튠) / scan_categories / discover_brands 5종 전부 |
| 단위테스트 | ✅ 62/62 PASSED |
| 라이브 검증 | ✅ 07-13 실측: search 36건, detail 옵션2·이미지6, brands 319, categories 1,362, refresh 전 필드 정상 |
| 계정등록·송장수집 | ✅ 이미 main 병합됨 (750364225, 242fd5eb6, 78e8eeddd) |
| 프론트 | 수집 드롭다운 `THEHYUNDAI` 존재하나 `disabled: true` |
| 배포 | ⏳ 미배포 |

## 2. ★2026-07 사이트 변경 (07-13 실측, 원본 문서와 다름)

- 원본의 "인증/UA/Referer/Cookie 불필요, 전 GET 익명 200"은 **더 이상 사실 아님**:
  `/proxy/*` GET 이 **Referer 미포함 시 HTTP 500**. 값은 아무 URL이나 통과.
  → `_client()` 기본 헤더(UA/Referer/Accept)로 대응 완료 (`bbd1cb8a6`).
- 검색 페이지 `/search/result?searchQuery=` → `/search?q=&tab=product` 변경.
  API 경로(`/proxy/v1/dp/search/searchResult`)·파라미터·응답구조는 불변.
- 나머지 기술 사실(NCP_PRODUCT 트랩, uitmStckList, bnftReCalcList 500 폴백,
  new_cost 공식, 확장앱 위임 없음)은 원본 그대로 유효.

## 3. ★옵션A(LOCAL_THEHYUNDAI_MODE) 재결정 — 구현 불필요

원본 옵션A의 정의: **맥미니 백엔드가 운영 DB(Cloud SQL)를 공유하며 2번째
인스턴스로 뜰 때**, device 격리 없는 위험 데몬(주문폴러·롯데홈QA·테트리스sync·
적립금auto·reconciler 5종·PC sync/cleanup/watch)이 양쪽 중복 실행되는 걸 막는
부분 비활성화 플래그. (`DISABLE_BACKGROUND_WORKERS=1`은 JobWorker/오토튠까지
꺼버려서 못 쓰는 게 전제였음)

| 원본 전제 | 현 상황 |
|---|---|
| 운영=VM (env gate off → 더현대 플러그인 미등록) | 운영=윈도우PC 로컬, 본인 전권 |
| 더현대 돌리려면 맥미니 2번째 백엔드 + 운영 DB 공유 필수 | **운영 컨테이너에 `ENABLE_THEHYUNDAI=1`만 켜면 운영 오토튠이 직접 더현대 refresh** |
| → 2-인스턴스 데몬 중복 위험 → 옵션A 필요 | → **단일 인스턴스, 중복 위험 자체가 소멸 → 옵션A 불필요** |

원본 §5 "운영 오토튠으로는 더현대 재고 업데이트 불가"도 현 인프라에선 무효
(운영이 곧 로컬이라 env만 켜면 가능).

**보존**: 위 위험 데몬 목록(원본 §6)은 향후 멀티워커/2-인스턴스 전환
(메모리 `autotune-transmit-connection-exhaustion`의 계획) 시 그대로 유효하므로
그때 재사용. 구현 위치는 `lifecycle.py` 각 데몬 startup 지점 env 가드.

## 4. 로컬-only 4중 안전장치 (원본 §4, 유지)

| # | 장치 | 동작 |
|---|---|---|
| 1 | env gate (`thehyundai.py:109-117`) | `ENABLE_THEHYUNDAI=1` 미설정 시 클래스 삭제 → 플러그인 미등록 |
| 2 | applied_policy_id 자연 격리 | 매핑 없으면 오토튠 사이클 진입 불가 |
| 3 | device_id 명시 시작 | 오토튠은 등록 PC만 사이클 발행 |
| 4 | 프론트 disabled:true | 드롭다운 비활성 |

→ 게이트는 "로컬 격리"에서 **"켜기 전 안전 스위치"**로 용도 전환해 유지.

## 5. 남은 작업 (순서대로)

1. **배포 브랜치 병합** — `feat/thehyundai-local` → 배포 계열. (Ul4YY 원본 브랜치는
   6/1 기준이라 464파일 갈라짐 — 직접 체크아웃 금지, cherry-pick 완료본 사용)
2. **윈도우PC 배포** — amd64 재빌드 → `save|ssh load` → compose에
   `ENABLE_THEHYUNDAI=1` 추가 → `--force-recreate` (메모리 `windows-deploy-procedure`).
3. **프론트 활성화** — `constants.ts` `disabled: true` 제거 → myfork push → Vercel.
4. **소싱 계정 등록** — `/accounts` (id "TheHyundai" → 정규화 THEHYUNDAI). 수집엔
   계정 불요(익명 API), 주문용.
5. **파일럿 수집** — 브랜드 단위 소량 → 카테고리 매핑 → 전송은 보고→확인 후.
6. **오토튠 편입** — 매핑 생기면 자동 사이클 진입. 시작/중지는 사장님 직접.

## 6. 보안 메모 (원본 §9 유지)

- 과거 세션에서 GitHub PAT 터미널 노출 → revoke 완료. SSH 키 방식 권장.
- `.env` 커밋 절대 금지 (.env.example만).

## 함정 메모

- 소싱처 우선순위: 무신사 > ABC > 롯데온 > 패플 > SSG > GS > **더현대** (최하위).
- 원본 §8 맥미니 기동 절차(Cloud SQL 접속, uv venv)는 운영이 로컬로 내려와
  **불필요** — 개발 테스트는 맥미니 `backend/.venv` + `ENABLE_THEHYUNDAI=1`로 충분.
- docs/ 는 gitignore — 이 문서 갱신 시 `git add -f` 필요.
