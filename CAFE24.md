# 카페24 플러그인 통합 가이드

> `feature/cafe24-plugin` 브랜치에서 추가된 카페24 마켓 연동 플러그인 설명서. PR 리뷰 전에 반드시 이 문서를 먼저 확인 부탁드립니다.

---

## 🎯 리뷰 포인트 3줄 요약

1. **공유파일 `shipment/service.py`에 cafe24 예외 3곳 추가** — 카페24는 플러그인 내부에서 카테고리를 자동 생성하므로 사전 매핑 검증이 없어야 함
2. **CDN 화이트리스트 + Referer 동적 처리** — 카페24는 원본 URL 저장 후 hotlink 방식이라 소싱처별로 Referer 헤더 분기 필요
3. **카테고리 4단계 구조 + 소싱처 세분류 활용** — 카페24 표준 분류 체계에 맞춰 신발/수영복/키즈/속옷 등 세분화

---

## ⚠️ 공유파일 수정이 반드시 필요한 이유 — `shipment/service.py` 3곳 cafe24 예외

카페24는 플러그인 내부에서 `get_or_create_category_chain`으로 카테고리를 **자동 생성**하므로 사전 매핑이 불필요합니다. 하지만 전송 검증 단계에서 `if not category_id` 체크에 걸리면 플러그인까지 도달하지 못하고 차단됩니다.

### 영향 범위 (하나라도 빠지면 해당 경로 전멸)

| 위치 | 경로 | 영향 |
|------|------|------|
| `shipment/service.py:1195` | `start_update` 내 카테고리 검증 | **최초 전송 + 오토튠 전송 모두 실패** (오토튠도 내부적으로 `start_update` 호출) |
| `shipment/service.py:1204` | 최하단 카테고리 코드 숫자 검증 | 카테고리 경로 문자열 단계에서 차단 |
| `shipment/service.py:2068` | `retransmit` 재전송 경로 | 실패 계정 재시도 시 차단 |

### 필요한 패턴

```python
# 1. start_update 경로 (:1195)
if not category_id and market_type not in ("playauto", "cafe24"):

# 2. 최하단 카테고리 검증 (:1204)
if (
    market_type not in ("coupang", "playauto", "cafe24")
    and not _lotteon_like
    and not str(category_id).isdigit()
):

# 3. retransmit 경로 (:2068)
if not category_id and account.market_type not in ("playauto", "cafe24"):
```

### 🚨 머지 시 주의사항

이 예외 처리는 이미 **2번 유실**되었습니다:
- `7138fc6a` (4/8) — 1차 유실 복원
- `a5e751c8` (4/15) — 2차 유실 복원

main을 머지할 때 `shipment/service.py`가 `--theirs`(main 버전)로 채택되면 cafe24 예외가 사라집니다. 머지 후 반드시 다음 명령으로 3곳 존재 확인:

```bash
grep -n 'cafe24' backend/backend/domain/samba/shipment/service.py
```

---

## 📐 카페24 특이사항 9가지 (다른 마켓과 다른 동작)

### 1. 카테고리 매핑 불필요 — 플러그인 내부 자동 생성

다른 마켓(쿠팡/스마트스토어/11번가 등): 사전에 카테고리 매핑 필수
→ 카페24: 소싱처 카테고리 경로(예: `여성 > 신발 > 러닝화`)를 받아 `get_or_create_category_chain`으로 카페24 카테고리 체인을 그 자리에서 생성/조회

### 2. 이미지 Referer 동적 처리 — hotlink 대응

카페24는 이미지를 자체 호스팅하지 않고 **원본 URL을 그대로 저장**, 프론트 노출 시 원본에서 로드.
소싱처별 CDN이 hotlink 방지를 걸어놓았기 때문에 전송 시 Referer 헤더를 소싱처별로 동적 세팅 (`proxy/cafe24.py`).

### 3. 이미지 CDN 화이트리스트

허용된 9개 소싱처 CDN만 전송:
- 무신사(`image.msscdn.net`), KREAM, ABC마트, SSG, 롯데ON, GS샵, 이랜드몰, SSF샵, 패션플러스
- 그 외 URL은 필터 제거 (차단 이미지 전송 방지)

### 4. 상세페이지 이미지 fallback 로직

`detail_images`와 `images` 배열이 중복되는 소싱처(네이버스토어 등)가 존재 → 필터 후 `_clean_images`가 빌 경우 `images[0]`로 fallback하여 상세페이지 템플릿 대표 이미지 누락 방지.

### 5. 카테고리 레벨 연속 중복 제거

소싱처에서 "러닝화 > 러닝화" 같은 연속 중복 경로가 오는 경우 자동 병합 (예: `["신발", "스포츠/아웃도어화", "러닝화", "러닝화"]` → `["신발", "스포츠/아웃도어화", "러닝화"]`).

### 6. 카테고리 4단계 구조 + 소싱처 세분류 활용

카페24 표준 분류 체계에 맞춰 신발/수영복/키즈/속옷/홈웨어 등 소싱처 원본 세분류(2~4레벨)를 활용:
- 신발: 구두/스니커즈/부츠/러닝화 세분화, 성별 구분
- 수영복: 남성수영복/여성수영복 중분류
- 키즈: 3단계 세분류 + 원피스/스커트 분리
- 속옷/홈웨어: 상의/하의/세트/브라/팬티 키워드 기반 분기

### 7. 중복 등록 방지 3단계

1. DB `market_product_nos` 체크 (우리 쪽 등록 이력)
2. 카페24 API 상품코드 조회 (타임아웃 후 재전송 대응)
3. 메모리 캐시 (같은 배치 내 동시 등록 중복 차단)

### 8. 제조사명 30자 제한

카페24 API가 제조사명 30자 초과 시 거부 → 자동 정제 로직으로 축약 후 전송.

### 9. OAuth 토큰 방식

다른 마켓(API Key) 대비 카페24는 OAuth 2.0 사용 → 액세스 토큰 + 리프레시 토큰 갱신 플로우 구현.

---

## 📂 PR 포함 파일 분류

### 담당 파일 (카페24 전용)
- `backend/backend/domain/samba/plugins/markets/cafe24.py` — 플러그인 본체 (등록/수정/삭제/카테고리 생성)
- `backend/backend/domain/samba/proxy/cafe24.py` — API 클라이언트 (OAuth, 이미지 업로드, Referer 처리)

### 공유 파일 수정 (검토 필요)
- `backend/backend/domain/samba/shipment/service.py` — cafe24 카테고리 예외 3곳 (위 상세 설명 참고)
- `backend/backend/domain/samba/category/service.py` — 카페24 카테고리 매핑 관련

### DB 마이그레이션
- `backend/alembic/versions/810ee4ec3d0b_add_ss_brand_manufacturer_to_search_.py`
- `backend/alembic/versions/c4f2407a01_add_board_no_to_samba_cs_inquiry.py`

### 프론트엔드
- `frontend/src/app/samba/products/components/ProductCard.tsx` — cafe24 마켓 뱃지 표시
- `frontend/src/app/samba/returns/page.tsx` — cafe24 반품 지원
- `frontend/src/lib/samba/constants.ts` — cafe24 마켓 타입 상수

### PR 제외 (본인 개발 환경 전용)
- `.github/workflows/deploy-cloudrun.yml` (본인 GCP 프로젝트)
- `frontend/.env.production` (본인 Cloud Run URL)
- `.claude/settings.local.json` (로컬 툴 설정)
- `.gitignore`, `CAFE24_ROADMAP.md` (개인 작업 파일)
- `[LOCAL-ONLY]`, `chore: 재배포 트리거` 커밋들

---

## 🛠️ 카페24 세팅 & 사용법

### 1. 카페24 개발자센터 — 앱 생성

**1-1. 앱 기본 정보 등록**
- 사이트 URL (예시): `https://samba-wave-theta.vercel.app`
- Redirect URI (예시): `https://samba-wave-api-405469226128.asia-northeast3.run.app/api/v1/samba/proxy/cafe24/callback`

**1-2. 권한 선택 (읽기 + 쓰기)**
아래 스코프 전부 체크:
- 앱 / 상품분류 / 상품 / 판매분류 / 공급사정보 / 주문 / 게시판 / 회원 / 알림 / 디자인 / 배송

**1-3. 발급 확인**
- 앱 생성 완료 후 `Client ID` / `Client Secret` 자동 발급

---

### 2. 쌈바 설정

**2-1. 카페24 계정 연동**
1. 쌈바 관리자 → 카페24 계정 등록 화면 진입
2. `Client ID` / `Client Secret` / `Redirect URI` 입력
3. **인증테스트** 클릭
4. **OAuth 인증** 클릭 → 카페24 로그인 + 권한 승인
5. 인증 완료되면 **설정 저장**

---

### 3. 카페24 카테고리 매핑 정책

**3-1. 매핑이 아닌 "자동 생성" 방식 채택**
- 카페24는 다른 마켓과 달리 카테고리 "매핑" 개념 없음 → 전송 시점에 **자동 생성**으로 처리
- **자사몰 특성상 대분류가 제한적** (예: 아우터 / 상의 / 하의 / 슈즈 / 악세사리 / ETC)
- 기존 매핑 방식을 그대로 적용하면 대분류가 수백 개로 폭증하여 운영 불가 → 생성형으로 전환

**3-2. 4단계 카테고리 구조 (대분류 / 중분류 / 소분류 / 세분류)**
- 소싱처별 카테고리 체계가 매우 방대하여 **수동으로 카테고리 체계 정의**
- **패션 카테고리**: 평균적으로 기본 생성 완료 (신발/수영복/키즈/속옷/홈웨어 등 성별·유형 세분화)
- **그 외 카테고리**: 사용자가 등록하며 필요 시 추가·수정 보완 필요

---

### 4. 오토튠 (자동 가격·재고 동기화)

**4-1. 동작 개요**
- 소싱처(무신사 등)를 주기적으로 재수집하여 **가격/재고 변동을 감지**
- 변동 감지 시 카페24로 자동 전송하여 판매가·옵션 재고 최신 상태 유지

**4-2. 감지 → 전송 흐름**
1. 소싱처 상품 재수집 (원가, 최대할인가, 옵션별 재고 비교)
2. DB 대비 변동분만 추출 (가격 / 재고 / 품절)
3. 카페24로 전송 — **가격과 재고를 같은 큐에서 병합 전송** (중복 lock 방지)
4. 전송 결과 로그 + 가격·재고 이력 테이블 기록

**4-3. 카페24 특화 동작**
- **품절 처리**: 소싱처 옵션 재고 0 → 카페24 해당 옵션 `selling=F` 처리
- **전량 품절**: 모든 옵션 품절 → 카페24 상품 **판매중지** (마켓삭제 아님)
- **재입고**: 품절 옵션에 재고 복귀 시 `selling=T`로 복구
- **가격 변동**: 최대할인가 변경 시 판매가 자동 갱신

**4-4. ⚠️ 카테고리 예외 처리 필수**
- 오토튠 동작 중 "카테고리 매핑 없음" 오류가 발생한 것으로 보아 **오토튠 내부에도 카테고리 반영 단계가 있는 것으로 추정**
- 카페24는 **카테고리 매핑 없이 등록하는 케이스**이므로, 오토튠 시 카테고리 검증·반영이 일어나지 않도록 예외 처리
- 구체적으로는 `shipment/service.py` 3곳에 cafe24 예외를 추가하여 오토튠 내부에서 호출되는 `start_update` / `retransmit` 경로가 모두 카테고리 없이 통과되도록 함
- 위 [공유파일 수정이 반드시 필요한 이유](#️-공유파일-수정이-반드시-필요한-이유--shipmentservicepy-3곳-cafe24-예외) 참조

---

### 5. 주문 / CS

**5-1. 기존 마켓의 주문·CS 수집 방식 (참고)**
- 스스/쿠팡/11번가 등 오픈마켓: 마켓이 제공하는 **주문 API 하나**로 계정 전체 주문을 일괄 수집
- CS도 마켓 공용 Q&A API 하나로 통일된 형태(`inquiry_no` / `writer` / `content`)로 수집
- `order.py`의 `_parse_XXX_order()` 패턴으로 마켓별 분기만 추가하면 동일 로직 재사용 가능

**5-2. 카페24가 다른 점 — 자사몰 특성상 API 구조가 전혀 다름**

| 항목 | 기존 오픈마켓 | 카페24 |
|------|--------------|--------|
| 주문 스코프 | 계정 단위 | **샵 단위(`shop_no`) + 브랜드 단위(`brand_no`)** |
| 주문 식별 | 주문번호 하나 | 주문번호 + 샵번호 + 품목번호 조합 |
| 브랜드 필터 | 불필요 | 소싱처 브랜드별 분기 필요 — 자사몰에 여러 브랜드 상품이 섞여 있어 **`brand_no`로 필터링** 안 하면 남의 브랜드 주문까지 끌려옴 |
| CS 조회 | 공용 Q&A API | 게시판 시스템 — **`board_no` 기반 조회** |

**5-3. CS(상품문의) 수집 — 2단계 fallback 구현 (`proxy/cafe24.py` L672~)**

카페24 CS API는 일반 앱에서 막혀 있어서 **게시판 우회 경로**를 구현해야 했습니다.

1. **1차 시도**: `GET /inquiries` (`mall.read_inquiry` 스코프)
   - 공식 상품문의 API지만 **일반 앱 미지원** → 권한 부족으로 실패하는 경우가 많음
2. **2차 fallback**: `GET /boards/{board_no}/articles` (`mall.read_community` 스코프)
   - 게시판 목록(`/boards`)에서 이름에 `문의 / inquiry / 상품문의 / q&a` 키워드 포함된 게시판을 찾아 `board_no` 확보
   - 해당 게시판의 게시물을 읽어 기존 `inquiry` 형식으로 변환 (`inquiry_no` ← `article_no`, `writer_name` ← `writer` 등)

> **→ OAuth 권한에 `게시판(read_community)`를 반드시 포함해야 하는 이유** (1-2 권한 목록 참조)

**5-4. CS 답변 쓰기도 게시판 댓글 API 사용**
- `POST /boards/{board_no}/articles/{article_no}/comments` (`proxy/cafe24.py` L1070)
- 기존 마켓은 공용 "Q&A 답변 API" 하나였지만, 카페24는 **게시판 댓글 시스템**을 그대로 씀

**5-5. 현재 구현 상태 & 후속 작업**
- OAuth 권한에 **주문 / 게시판 / 회원 / 알림** 포함 (1-2 참조) — 권한은 모두 확보됨
- CS 수집·답변 로직: ✅ 구현 완료 (`proxy/cafe24.py`의 `get_product_inquiries` / `post_inquiry_reply`)
- 주문 수집 로직: ⚠️ `order.py` 쪽 cafe24 분기는 본 PR에 포함되지 않음 → **후속 PR에서 `brand_no` 필터 + `shop_no` 처리 추가 예정** (팀장님 공유파일 수정 범위 사전 검토 필요)

---

## ✅ 테스트 체크리스트

### 최초 전송
- [ ] 무신사 상품 수집 → 카페24 전송 → 상품코드 생성 확인
- [ ] 옵션별 재고/가격 정상 반영 확인
- [ ] 상세페이지 이미지 노출 확인 (대표 이미지 + 추가 이미지)
- [ ] 카테고리 경로 자동 생성 확인 (카페24 관리자 화면)

### 오토튠 (재전송)
- [ ] 가격 변동 감지 → cafe24 전송 성공 (카테고리 매핑 에러 없음)
- [ ] 재고 변동(품절 포함) → cafe24 반영 확인
- [ ] 가격+재고 동시 변동 → 둘 다 반영 확인

### 에러 케이스
- [ ] 소싱처 상품 삭제 → cafe24 판매중지 처리
- [ ] 이미지 CDN 허용 외 URL → 필터링 확인
- [ ] 제조사명 30자 초과 → 자동 축약 후 등록 성공

---

## 🔗 관련 커밋 (주요 이정표)

| 커밋 | 내용 |
|------|------|
| `5046c1c6` | 카페24 플러그인 최초 구현 — 마켓삭제, 카테고리 자동생성, 대표이미지 업로드 |
| `7138fc6a` | 공유파일 cafe24 예외 1차 복원 (머지 유실) |
| `1a6f32d0` | 카페24 카테고리 4단계 구조 전면 개편 |
| `635eedab` | 중복 등록 방지 — API 상품코드 조회 |
| `6f7ee181` | 중복 방지 3단계 — 메모리 캐시 배치 내 차단 |
| `5a4b47e8` | CDN 화이트리스트 확장 — 9개 소싱처 지원 |
| `44b1b4ca` | retransmit 경로 cafe24 예외 추가 |
| `78e3acf4` | 상세페이지 대표이미지 fallback |
| `333f6ed4` | 카테고리 연속 중복 제거 + 러닝화 스포츠화 이동 |
| `a5e751c8` | 공유파일 cafe24 예외 2차 복원 (머지 유실) |
