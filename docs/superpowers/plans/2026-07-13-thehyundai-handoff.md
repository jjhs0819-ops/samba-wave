# 더현대Hi 소싱처 개발 핸드오프 (2026-07-14 갱신, 현 인프라 보정판)

> 원본(myfork `claude/sourcing-site-analysis-Ul4YY` 커밋 `316dfe5fe`, 205줄)은
> **VM 운영 + Cloud SQL 공유 + 맥미니 로컬 백엔드** 전제로 작성됨.
> 2026-06-27 윈도우PC 로컬 이사로 전제가 바뀌어 이 보정판으로 대체.
> 원본 전문은 `git show 316dfe5fe:docs/superpowers/plans/2026-07-13-thehyundai-handoff.md`.

## 1. 현재 상태 (2026-07-14 심야 기준)

| 항목 | 상태 |
|---|---|
| 플러그인+수집 파이프라인 | ✅ `feat/thehyundai-local` 브랜치 — cherry-pick + 수집통합 + 버그수정 + 심야 보강 전부 완료 |
| 구현 범위 | search/get_detail/refresh(오토튠)/scan_categories/discover_brands 5종 + UI 스캔·브랜드모달·그룹생성·잡워커 수집 전 경로 |
| 부가 필드 | ✅ mndrInfoList 연동 — material/color/manufacturer/origin/care/quality/style_code + sex 추정 + 이미지 1000px |
| 단위테스트 | ✅ 80/80 PASSED |
| 오토튠 | ✅ 가상 테스트 — SOURCING_PLUGINS 디스패치 + 실상품 10건 refresh 10/10 정상(건당 0.21s), 유령상품 deleted 게이트 정상, refresh 는 mndr 미호출(부하 無) |
| 실수집 | ✅ 나이키 10건 운영 수집·보존 (그룹 "더현대_나이키_10") — 단 부가필드 보강 전 수집분이라 재배포 후 재수집 권장 |
| **배포** | ⏳ **07-13 오후 `4ae5a61df`(가격수정)+`e37e570d0`(원문링크) 시점까지만 운영 반영됨. 심야 보강 5커밋(a04ac711~)은 미배포 — 사장님 일괄 배포 대기.** 프론트도 `ebe6d3d25`까지만 Vercel 반영, 브랜드모달 커밋 미배포 |

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

## 5. 수집 방식·속도 결론 (2026-07-14 심야 분석)

- **더현대 = 직접 httpx API 방식** (무신사/패플/Nike/SSG 계열). 데몬(ABC·롯데온:
  WAF/차단 우회용)·확장앱(GSShop: 소싱큐)은 인증/차단 문제가 있을 때 쓰는 우회로인데
  더현대는 Referer 헤더만으로 전 API 접근 가능 → **직접 API 가 최적, 전환 불필요**.
- 07-13 실수집이 느렸던 원인 2가지:
  ① 더현대만 상세 **선취합(prefetch) 배치 미적용** — per-item 직렬 조회(+0.3s sleep).
     → **8건 병렬 선취합 추가로 해결** (`a04ac7116`). Nike(10)/GSShop(20)/SSG와 동급.
  ② 오토튠 피크(잡 큐 2,000+건)의 쓰기 DB 풀 경합 — 전 소싱처 공통, 더현대 무관.
- 상세 1건 = detail + (uitmStck) + maxBnft + mndr 4 hop 인데 **3개 병렬화** 완료.
  로컬 실측 건당 0.2~1.3s, 오토튠 refresh 는 건당 0.21s.

## 6. 남은 작업 (순서대로)

1. **일괄 배포 (사장님)** — 백엔드: `feat/thehyundai-local` 심야 5커밋 포함 재빌드
   (`a04ac7116` prefetch / `28ae779a9` 고시 / `ff40f6bd0` 브랜드모달+파이프 /
   `4415300a4` 이미지1000px / `89927b514` 성별). 프론트: myfork main 푸시 → Vercel
   (브랜드모달 배선 커밋 포함 필요).
2. **기존 10건 재수집** — 부가필드 보강 전 수집분이라 그룹 삭제 후 재수집하면
   고시·스타일코드·1000px 이미지로 채워짐.
3. **파일럿 계속** — 카테고리 매핑 확인 → 전송은 보고→확인 후.
4. **오토튠 편입** — 매핑 생기면 자동 사이클 진입. 시작/중지는 사장님 직접.

## 7. 보안 메모 (원본 §9 유지)

- 과거 세션에서 GitHub PAT 터미널 노출 → revoke 완료. SSH 키 방식 권장.
- `.env` 커밋 절대 금지 (.env.example만).

## 함정 메모

- 소싱처 우선순위: 무신사 > ABC > 롯데온 > 패플 > SSG > GS > **더현대** (최하위).
- **flBrand 다중 구분자는 파이프(|)** — 쉼표는 서버가 조용히 0건 반환 (실측).
- 이미지 서버 `?RS=WxH` 리사이즈 지원 (기본 600, 실원본 2000+). 수집은 1000 고정.
- 필수고시는 detail 이 아니라 `/proxy/v1/pd/item/inf/mndrInfoList` 별도 API.
  `brndBcdVal` = 스타일코드.
- 잡 완료 직전 InterfaceError 로 status 가 "failed" 로 떠도 데이터는 정상 저장
  (전 소싱처 공통 cosmetic). 진행 카운터 cur=0 표시도 동일.
- **myfork main 푸시 = Vercel 자동배포** — "배포 금지" 상황에선 feat 브랜치만 푸시.
- 원본 §8 맥미니 기동 절차(Cloud SQL 접속, uv venv)는 운영이 로컬로 내려와
  **불필요** — 개발 테스트는 맥미니 `backend/.venv` + `ENABLE_THEHYUNDAI=1`로 충분.
- docs/ 는 gitignore — 이 문서 갱신 시 `git add -f` 필요.
