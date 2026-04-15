# CLAUDE.md — Samba Wave 개발 표준

> Claude Code(claude.ai/code)가 이 저장소에서 작업할 때 반드시 준수해야 하는 개발·배포·보안 표준 문서입니다.

---

## 목차

1. [프로젝트 구조](#1-프로젝트-구조)
2. [기술 스택](#2-기술-스택)
3. [로컬 개발 환경 설정](#3-로컬-개발-환경-설정)
4. [빌드 · 린트 · 테스트 명령어](#4-빌드--린트--테스트-명령어)
5. [아키텍처 개요](#5-아키텍처-개요)
6. [개발 워크플로우](#6-개발-워크플로우)
7. [코드 작성 규칙](#7-코드-작성-규칙)
8. [배포/보안/마이그레이션 → CLAUDE-DEPLOY.md](./CLAUDE-DEPLOY.md)

---

## 1. 프로젝트 구조

```
samba-wave/                    # 모노레포 루트
├── backend/                   # Python FastAPI 백엔드
│   ├── backend/
│   │   ├── api/v1/routers/   # API 라우터 (samba 도메인별)
│   │   ├── core/config.py    # 환경변수 기반 설정 (Pydantic BaseSettings)
│   │   ├── db/orm.py         # Read/Write DB 세션 팩토리
│   │   ├── domain/samba/     # 핵심 비즈니스 로직 (DDD)
│   │   │   ├── collector/    # 상품 수집
│   │   │   ├── policy/       # 가격 정책
│   │   │   ├── shipment/     # 발송 처리
│   │   │   ├── order/        # 주문 관리
│   │   │   ├── account/      # 계정 관리
│   │   │   ├── category/     # 카테고리 매핑
│   │   │   ├── proxy/        # 마켓 API 연동 (elevenst, coupang 등)
│   │   │   └── plugins/      # 소싱사이트별 수집 플러그인
│   │   └── dtos/             # Request/Response DTO
│   ├── alembic/              # DB 마이그레이션
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/                  # Next.js 15 프론트엔드
│   ├── src/app/              # App Router 페이지
│   │   └── samba/            # Samba Wave 메인 기능
│   ├── src/components/
│   ├── src/lib/
│   │   ├── api.ts            # API 클라이언트
│   │   └── samba/api.ts      # Samba 도메인 API
│   └── src/hooks/
└── .github/workflows/
    └── deploy-cloudrun.yml   # CI/CD 파이프라인
```

---

## 2. 기술 스택

| 영역 | 기술 |
|------|------|
| 백엔드 프레임워크 | FastAPI (async/await) |
| ORM | SQLModel + SQLAlchemy (asyncpg) |
| DB | PostgreSQL (Cloud SQL, Read/Write 분리) |
| 프론트엔드 | Next.js 15 (App Router), React 19 |
| 스타일링 | Tailwind CSS 4, MUI Material |
| 인증 | JWT (서버사이드 검증) |
| 파일 스토리지 | Cloudflare R2 |
| 배포 (백엔드) | Google Cloud Run |
| CI/CD | GitHub Actions |
| 패키지 관리 (BE) | uv (Python 3.12.3) |
| 패키지 관리 (FE) | pnpm |

---

## 3. 로컬 개발 환경 설정

### 백엔드

```bash
cd backend

# 가상환경 생성 및 패키지 설치
uv venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
uv pip install -e .
uv pip install -e .[dev]

# 환경변수 설정 (.env 파일 생성 — 절대 Git 커밋 금지)
cp .env.example .env               # 없으면 아래 섹션의 목록 참고

# 개발 서버 실행
uvicorn backend.main:app --reload --port 28080
```

### 프론트엔드

```bash
cd frontend
pnpm install

# 환경변수 설정
cp .env.example .env.local

# 개발 서버 실행
pnpm dev    # http://localhost:3000/samba
```

> **중요:** 로컬 접속 주소는 항상 `http://localhost:3000/samba`

---

## 4. 빌드 · 린트 · 테스트 명령어

### 백엔드

```bash
cd backend

# 코드 포맷
black .
isort . --profile black

# 린트 (자동 수정 포함)
ruff check --fix .

# 타입 체크
mypy .

# 전체 pre-commit 훅 실행
pre-commit run --all-files

# DB 마이그레이션 생성 (모델 변경 후)
alembic revision --autogenerate -m "변경 내용 설명"

# DB 마이그레이션 적용
alembic upgrade head
```

### 프론트엔드

```bash
cd frontend

# 빌드
pnpm build

# 린트
pnpm lint

# 프로덕션 서버 (빌드 후)
pnpm start
```

---

## 5. 아키텍처 개요

### 백엔드 아키텍처

**도메인 주도 설계 (DDD):**
- 각 도메인 디렉토리는 `model.py` / `service.py` / `repository.py` 3-레이어 구조
- 비즈니스 로직은 `service.py`에만 위치, `repository.py`는 순수 데이터 접근만 담당

**DB 세션 규칙:**
- 데이터 수정 엔드포인트 → `get_write_session_dependency()`
- 조회 전용 엔드포인트 → `get_read_session_dependency()`
- 두 세션을 절대 혼용하지 말 것

**마켓 연동 구조:**
- `proxy/elevenst.py`, `proxy/coupang.py` 등 마켓별 파일에서 XML/API 변환 처리
- `plugins/markets/` — 등록/수정/삭제 액션
- `plugins/sourcing/` — 소싱사이트 수집 플러그인

### 프론트엔드 아키텍처

**Next.js App Router 기반:**
- Server Component / Client Component 명확히 구분
- API 호출은 `src/lib/samba/api.ts` 를 통해 중앙화
- 인증: `src/lib/serverAuth.ts` (서버사이드 JWT 검증)

---

## 6. 개발 워크플로우

### 브랜치 전략

```
main (단일 브랜치)
 └─ 로컬에서 수정 → 로컬 검증 → push → 자동 배포
```

**브랜치를 별도로 나누지 않는다.** `main`에 직접 작업하되, 로컬에서 충분히 검증한 후 push한다.

### Push 기준 (마일스톤 단위)

다음 조건을 모두 만족할 때만 `main`에 push한다:

- [ ] 로컬 백엔드 서버에서 해당 기능 정상 동작 확인
- [ ] 로컬 프론트엔드에서 UI/UX 정상 동작 확인
- [ ] 새로운 DB 컬럼/테이블 추가 시 → Alembic 마이그레이션 파일 생성 완료
- [ ] 새로운 환경변수 추가 시 → GitHub Secrets 등록 완료 + 이 문서의 [환경변수 목록](#10-️-cloud-run-환경변수-관리) 업데이트

### Push 명령어

```bash
git add .
git commit -m "커밋 메시지 (한국어)"
git push origin main
```

push 후 GitHub Actions 배포 완료까지 약 3~5분 소요. Cloud Run 로그에서 확인.

---

## 7. 코드 작성 규칙

### 언어

- 응답 및 주석: **한국어**
- 변수명/함수명: **영어** (코드 표준 준수)
- 커밋 메시지: **한국어**

### 중요 규칙

- **삭제(마켓삭제)** ≠ **판매중지(SUSPENSION/STOP)** — 절대 혼동하지 말 것
- DB 세션은 반드시 Read/Write 분리 사용
- 새 API 엔드포인트 추가 시: DTO → Repository → Service → Router 순서로 작성
- 마켓 API 연동 작업 전 **반드시 공식 API 문서 먼저 확인** — 추정 기반 구현 금지
- 모달은 반드시 모달창(팝업 X)으로 구현
- 스피너 사용 금지

### 백엔드 모듈 경로

```bash
# 올바른 실행 방법
uvicorn backend.main:app --reload --port 28080

# 틀린 방법 (사용 금지)
uvicorn app.main:app ...
```

### DB 컬럼 추가 체크리스트

1. `model.py` 필드 추가
2. `alembic revision --autogenerate` 실행
3. 마이그레이션 파일 검토 및 커밋
4. 로컬 `alembic upgrade head` 확인
5. push (CI/CD가 자동으로 프로덕션 DB에 적용)
