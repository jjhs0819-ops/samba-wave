# 더현대(TheHyundai) 소싱처 개발 — 핸드오프 문서

> 새 세션에서 이어서 작업하기 위한 정리. 마지막 업데이트: 2026-07-13

---

## 1. 목표 (한 줄)

더현대(hi.thehyundai.com) 소싱처를 **로컬(맥미니)에서만** 수집·매핑·전송하고,
운영 배포 환경 코드는 원작자 풀링해도 그대로 돌아가게 한다. 명령은 Claude Code로 진행.

---

## 2. 현재 상태

| 항목 | 상태 |
|------|------|
| 브랜치 | `claude/sourcing-site-analysis-Ul4YY` |
| 더현대 코드 커밋 | `932ef54` — "feat(소싱/더현대Hi): 신규 소싱처 통합 — 로컬-only 운영 (env var gate)" |
| 코드 규모 | 12개 파일, +1864줄 (단위 테스트 62 PASSED) |
| 원격 위치 | `jjhs0819-ops/samba-wave` (맥미니에선 remote 이름 `myfork`) |
| **미완료 작업** | 부분 비활성화 플래그(`LOCAL_THEHYUNDAI_MODE`) 신규 추가 — **아직 안 함** |

### 맥미니 remote 구성 (주의!)
```
origin  → github.com/sbk0674-web/samba-wave      (원작자 레포)
myfork  → github.com/jjhs0819-ops/samba-wave     (내 작업 레포) ← 더현대 코드는 여기
```
→ 브랜치 받을 때 `git fetch myfork claude/sourcing-site-analysis-Ul4YY`

---

## 3. 커밋 932ef54가 구현한 것

| 함수 | 역할 |
|------|------|
| `search()` | keyword/URL/카테고리/브랜드 검색. `searchType=NCP_PRODUCT` 필수 트랩 대응 |
| `get_detail()` | detail + (uitmCombYn="1") uitmStckList + maxBnftList 머지 |
| `refresh()` | RefreshResult 전 필드. price_uncertain·deleted_from_source 가드 |
| `scan_categories()` | searchFilterInfo 1회로 4단계 트리 평탄화 + 여행/E쿠폰 SKIP |
| `discover_brands()` | brandList → operBrndCd canonical key 정규화 |

### 기술 사실 (사이트 조사 결과)
- 단일 도메인 `hi.thehyundai.com` (www/m 모두 리다이렉트)
- **순수 httpx 직접 호출** (MUSINSA 패턴). 인증/UA/Referer/Cookie **불필요** (전 GET 익명 200)
- **확장앱 큐 위임 안 씀** ← 중요
- 검색 트랩: `searchType=NCP_PRODUCT` 미지정 시 productList 미반환
- 다차원 옵션: `uitmStckList` 필수 (uitmAttrList는 1차원만)
- `bnftReCalcList` HTTP 500(서버 버그) → `uitmAttrList[n].uitmDcPrc` 폴백
- new_cost 공식: `aplyDcPrc − Σ(step8a.dcAmt) − Σ(step8b.dcAmt)` (SSG bestBenefitPrice 선례)

### 변경 파일 목록
```
backend/backend/api/v1/routers/samba/collector_collection/brands.py   (+11)
backend/backend/api/v1/routers/samba/sourcing_account.py              (+7)
backend/backend/domain/samba/collector/refresher.py                  (+7)
backend/backend/domain/samba/plugins/sourcing/thehyundai.py          (+119)  ← 플러그인 등록/게이트
backend/backend/domain/samba/proxy/thehyundai_sourcing.py            (+733)  ← 핵심 로직
backend/backend/domain/samba/sourcing_account/model.py               (+1)
backend/scripts/diag_thehyundai_autotune.py                          (+162)  ← 진단 스크립트
backend/tests/test_thehyundai_*.py                                   (4파일, 62 테스트)
frontend/src/app/samba/collector/constants.ts                        (+6)   ← disabled:true
```

---

## 4. 로컬-only 4중 안전장치 (이미 구현됨)

| # | 장치 | 위치 | 동작 |
|---|------|------|------|
| 1 | **env var gate** | `thehyundai.py:109-117` | `ENABLE_THEHYUNDAI=1` 미설정 시 `TheHyundaiPlugin` 클래스 자체 삭제 → `discover_plugins()`가 못 찾음 → `SOURCING_PLUGINS` 미등록 |
| 2 | applied_policy_id 자연 격리 | `_get_active_sites_cached` (:81) | 매핑 있는 상품의 source_site만 enumerate. 운영에 매핑 안 만들면 사이클 진입 불가 |
| 3 | PC instance 명시 시작 | 오토튠 `/autotune/start device_id=<로컬PC>` | device_id 미등록 PC는 사이클 미발행 |
| 4 | 프론트 disabled:true | `constants.ts` | UI 드롭다운 비활성 (운영자 실수 방지) |

→ **운영 배포 환경**: env 미설정 + 매핑 미생성 → 더현대 코드 경로 자연 차단. 풀링해도 안 깨짐. ✅

---

## 5. 핵심 결론 — 오토튠/재고 업데이트

**운영(클라우드) 오토튠으로는 더현대 재고 업데이트 불가. 맥미니 백엔드 오토튠(데몬 방식)만 가능.**

| 경로 | 가능? | 이유 |
|------|------|------|
| 운영 백엔드 — 데몬 | ❌ | env 미설정 → 플러그인 미등록 |
| 운영 백엔드 — 확장앱 | ❌ | 더현대는 확장앱 위임 분기 자체가 없음 (httpx 직접 호출) |
| **맥미니 백엔드 — 데몬** | ✅ | env=1 → 플러그인 등록 → 오토튠이 httpx로 더현대 refresh |
| 맥미니 백엔드 — 확장앱 | ❌ | 위임 분기 없음 |

**함의**: 맥미니 백엔드가 살아있어야 더현대 재고 최신 유지. 오프라인 시 stale (명시적 로컬-only 설계).

---

## 6. ⚠️ 미해결 위험 — 운영 DB 공유 시 데몬 중복 실행

**Cloud SQL `samba-wave-db2`(운영 DB)를 맥미니 백엔드가 공유하면, 백그라운드 데몬이 양쪽에서 동시 실행됨.**

### 안전한 것 (격리됨)
| 데몬 | 격리 방식 |
|------|-----------|
| JobWorker (전송) | DB 행락 `FOR UPDATE SKIP LOCKED` (`worker.py:548`) |
| 오토튠 사이클 | `device_id` 필터 (`collector_autotune.py:3539,3547,3877`) |
| 더현대 플러그인 | env gate + applied_policy_id |

### 위험한 것 (device 격리 없음 — 양쪽 동시 실행)
| 데몬 | 위치 | 위험 |
|------|------|------|
| 주문 폴러 | `lifecycle.py:1059`, `order/poller.py:296` | 카카오 알림 중복 / 마켓 API rate limit |
| 롯데홈 QA 폴러 | `lifecycle.py:1067` | 중복 호출 |
| 테트리스 sync | `lifecycle.py:563` (in-memory last_run) | 양쪽 매 인터벌 발행 |
| 적립금 auto loop | `lifecycle.py:963` | 양쪽 발행 |
| reconciler 5종 (ghost/pid/status) | `lifecycle.py:1133-1228` | 매핑 백필 충돌 |
| PC sync/cleanup/watch | `lifecycle.py:382/432/497` | DB↔메모리 경쟁 |
| _order_auto_sync_loop | `lifecycle.py:844` | tenant dedup 있으나 양쪽 진입 |

### 기존 플래그의 한계
`DISABLE_BACKGROUND_WORKERS=1` 플래그 존재 (`lifecycle.py:1363`, 주석 "두 인스턴스 동일 DB 중복 방지").
**하지만 이걸 켜면 JobWorker/오토튠도 꺼져서 더현대 전송 불가** → 목표와 정반대. 못 씀.

---

## 7. 다음 작업 (권고안 — 옵션 A)

**신규 부분 비활성화 플래그 추가**: 오토튠·JobWorker는 살리고 위험 데몬만 끔.

```
LOCAL_THEHYUNDAI_MODE=1  (신규, 맥미니 .env에만)
  → 주문폴러 OFF
  → 롯데홈QA폴러 OFF
  → 테트리스sync OFF
  → 적립금auto OFF
  → reconciler 5종 OFF
  → PC sync/cleanup/watch OFF
  (JobWorker, 오토튠, 더현대 플러그인은 ON 유지)
```

구현 위치: `lifecycle.py`의 각 데몬 startup 지점에 `if os.getenv("LOCAL_THEHYUNDAI_MODE") != "1":` 가드 추가.
env로만 갈리므로 원작자 풀링 시에도 안 깨짐.

### 대안
| 옵션 | 내용 | 트레이드오프 |
|------|------|--------------|
| A (추천) | LOCAL_THEHYUNDAI_MODE 플래그 신규 | 코드 변경 1~2h. 풀링 안전 |
| B | 별도 DB(dev) 격리 | 데이터 분리 → 운영에서 더현대 상품 못 봄 |
| C | DISABLE_BACKGROUND_WORKERS=1 + 더현대 수동 호출 | 안전하나 자동수집/전송 불가 |

---

## 8. 맥미니 로컬 기동 절차

### 환경 이슈 (이전 세션 발견)
- `dev:backend` npm 스크립트가 **Windows 전용** (`.venv\Scripts\python.exe`) → macOS에선 수동 기동
- user의 `python3`는 uv로 설치됨 → 표준 `python3 -m venv`가 PEP 668 + ensurepip로 깨짐 → **uv venv 사용**
- `backend/.env` 없음 → `.env.example`(1910B) 복사해서 시작. DB는 Cloud SQL 값으로 채워야 함

### 기동 순서
```bash
# 0) 브랜치
cd ~/workspace/samba-wave
git fetch myfork claude/sourcing-site-analysis-Ul4YY
git checkout claude/sourcing-site-analysis-Ul4YY   # 또는 -b (최초 1회)

# 1) .env 준비
cp backend/.env.example backend/.env
echo "ENABLE_THEHYUNDAI=1" >> backend/.env
# echo "LOCAL_THEHYUNDAI_MODE=1" >> backend/.env   ← 옵션A 구현 후
# → backend/.env 의 WRITE_DB_*/READ_DB_* 를 Cloud SQL samba-wave-db2 값으로 수정

# 2) backend venv (uv 사용)
cd backend
rm -rf .venv
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements.txt

# 3) backend 기동
python run.py --reload --port 28080

# 4) frontend (별도 터미널)
cd ~/workspace/samba-wave/frontend && pnpm dev   # localhost:3000
```

### 미확정 정보 (다음 세션에서 user에게 확인)
- [ ] Cloud SQL `samba-wave-db2` 접속 방식: Cloud SQL Auth Proxy? public IP+SSL?
- [ ] DB 유저/패스워드/DB명 (`samba-wave-db2`가 인스턴스명인지 DB명인지)
- [ ] 운영 백엔드용 `.env`가 어딘가 있으면 그걸 복사하는 게 가장 안전

---

## 9. 보안 메모
- 이전 세션에서 GitHub PAT(`gho_...`)가 터미널에 노출됨 → user가 revoke 완료. 향후 SSH 키 방식 권장.
- `.env`는 절대 git 커밋 금지 (.env.example만 커밋).

---

## 10. 새 세션 시작 시 첫 프롬프트 (복붙용)

```
더현대 소싱처 개발 이어서 할게. docs/superpowers/plans/2026-07-13-thehyundai-handoff.md 읽고 시작해.
브랜치는 claude/sourcing-site-analysis-Ul4YY, 더현대 코드는 커밋 932ef54에 있어.
다음 작업: 섹션7 옵션A(LOCAL_THEHYUNDAI_MODE 플래그) 구현.
작업은 맥미니 로컬에서 Cloud SQL samba-wave-db2 공유하며 진행.
답변은 표로 요점만.
```
