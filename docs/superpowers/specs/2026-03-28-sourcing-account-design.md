# 소싱처 계정 관리 설계

## 개요

소싱처별 로그인 계정을 관리하여 주문 자동화의 기반을 마련한다.
무신사 10개 계정처럼 하나의 소싱처에 N개 계정을 등록하고, 크롬 프로필을 연결하여 Playwright 기반 자동화를 수행한다.

## 핵심 요구사항

- 소싱처별 N개 계정 등록 (아이디/비번/크롬 프로필)
- 무신사: 계정별 무신사머니 잔액 자동 조회
- 크롬 프로필 분리 방식으로 세션 유지 (캡챠 회피)
- 설정 탭 UI에서 계정 CRUD
- 추후 주문 자동화 확장 가능

## 지원 소싱처 (15개)

MUSINSA, KREAM, Nike, Adidas, ABCmart, OliveYoung, FashionPlus, GMARKET, SMARTSTORE, LOTTEON, GSShop, SSG, DANAWA + 추후 추가

## 데이터 모델

### `SambaSourcingAccount` (테이블: `samba_sourcing_account`)

| 필드 | 타입 | 설명 |
|------|------|------|
| id | str (PK) | `sa_ULID` |
| tenant_id | str? | 멀티테넌시 |
| site_name | str (NOT NULL, index) | 소싱처명 (MUSINSA, KREAM 등) |
| account_label | str (NOT NULL) | 별칭 ("무신사-기현") |
| username | str (NOT NULL) | 로그인 아이디 |
| password | str (NOT NULL) | 로그인 비밀번호 |
| chrome_profile | str? | 크롬 프로필 디렉토리명 ("Profile 1") |
| memo | str? | 쿠폰/용도 메모 |
| balance | float? | 잔액 (무신사머니 등) |
| balance_updated_at | datetime? | 마지막 잔액 조회 시각 |
| is_active | bool | 활성/비활성 (default: true) |
| additional_fields | JSON? | 소싱처별 확장 데이터 |
| created_at | datetime | 생성 시각 |
| updated_at | datetime | 수정 시각 |

## API 엔드포인트

### CRUD

| Method | Path | 설명 |
|--------|------|------|
| GET | `/sourcing-accounts` | 전체 목록 (site_name 필터 가능) |
| GET | `/sourcing-accounts/{id}` | 단건 조회 |
| POST | `/sourcing-accounts` | 계정 등록 |
| PUT | `/sourcing-accounts/{id}` | 계정 수정 |
| DELETE | `/sourcing-accounts/{id}` | 계정 삭제 |
| PUT | `/sourcing-accounts/{id}/toggle` | 활성/비활성 토글 |

### 크롬 프로필

| Method | Path | 설명 |
|--------|------|------|
| GET | `/sourcing-accounts/chrome-profiles` | PC에 존재하는 크롬 프로필 목록 반환 |

응답 예시:
```json
[
  { "directory": "Default", "name": "bkh9188" },
  { "directory": "Profile 1", "name": "cannonfort" },
  { "directory": "Profile 2", "name": "edelvise06" }
]
```

### 잔액 조회

| Method | Path | 설명 |
|--------|------|------|
| POST | `/sourcing-accounts/{id}/fetch-balance` | 단건 잔액 조회 |
| POST | `/sourcing-accounts/fetch-all-balances` | 특정 소싱처 전체 계정 잔액 조회 |

## 잔액 조회 흐름

```
요청 수신
→ DB에서 계정 정보 + chrome_profile 조회
→ Playwright launch(channel='chrome', userDataDir=크롬유저데이터경로, args=['--profile-directory=Profile X'])
→ 무신사 마이페이지 접속 (이미 로그인 상태)
→ 무신사머니 잔액 DOM 파싱
→ DB 업데이트 (balance, balance_updated_at)
→ 브라우저 닫기
→ 결과 반환
```

### 로그인 필요 시 (세션 만료)
```
마이페이지 접속 → 로그인 페이지로 리다이렉트 감지
→ 저장된 username/password로 자동 로그인
→ 성공 시 마이페이지 이동 → 잔액 조회
→ 실패 시 (캡챠 등) 에러 반환: "재로그인 필요"
```

## UI 설계 (설정 탭)

### 위치
기존 "스토어 연결" 섹션 하단에 **"소싱처 계정"** 섹션 추가

### 레이아웃
- 상단: 소싱처 탭 (무신사, KREAM, 나이키, ...)
- 계정 추가 버튼
- 계정 리스트 테이블:

| 별칭 | 아이디 | 크롬 프로필 | 잔액 | 조회시각 | 메모 | 활성 | 액션 |
|------|--------|------------|------|---------|------|------|------|
| 기현 | bkh9188 | Profile 1 | 52,300 | 3/28 14:30 | 신발쿠폰 | ON | 조회/수정/삭제 |

- "전체 잔액 조회" 버튼 → 활성 계정 순회하며 잔액 업데이트

### 계정 추가/수정 모달
- 소싱처 (선택, 읽기전용 if 수정)
- 별칭 (text)
- 아이디 (text)
- 비밀번호 (password)
- 크롬 프로필 (드롭다운, 서버에서 목록 로드)
- 메모 (textarea)

## 파일 구조

### 백엔드
```
backend/backend/
├── domain/samba/sourcing_account/
│   ├── model.py          # SambaSourcingAccount 모델
│   ├── repository.py     # DB 접근
│   └── service.py        # 비즈니스 로직 + Playwright 잔액 조회
├── api/v1/routers/samba/
│   └── sourcing_account.py  # API 라우터
└── dtos/samba/
    └── sourcing_account.py  # 요청/응답 DTO
```

### 프론트엔드
```
frontend/src/
├── lib/samba/api.ts      # sourcingAccountApi 추가
└── app/samba/settings/page.tsx  # "소싱처 계정" 섹션 추가
```

### DB 마이그레이션
```
alembic revision --autogenerate -m "add samba_sourcing_account table"
alembic upgrade head
```

## 기술 스택

- **Playwright**: `playwright.async_api` (Python) — 크롬 프로필 기반 브라우저 자동화
- **크롬 유저 데이터**: `%LOCALAPPDATA%/Google/Chrome/User Data/`
- **프로필 정보**: `{User Data}/Local State` JSON에서 프로필명 파싱

## 확장 고려사항

- 주문 자동화: 같은 Playwright + 크롬 프로필 방식으로 소싱처 주문 실행
- 소싱처별 잔액 조회 로직: site_name별 파서 분리 (무신사 마이페이지 DOM vs KREAM DOM)
- 소싱처별 추가 필드: additional_fields JSON으로 유연하게 대응
