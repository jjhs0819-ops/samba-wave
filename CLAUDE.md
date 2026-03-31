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
7. [🔒 보안 가이드라인](#7--보안-가이드라인)
8. [🚀 배포 체크리스트](#8--배포-체크리스트)
9. [🗄️ DB 마이그레이션 관리](#9-️-db-마이그레이션-관리)
10. [⚙️ Cloud Run 환경변수 관리](#10-️-cloud-run-환경변수-관리)
11. [코드 작성 규칙](#11-코드-작성-규칙)

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
# 또는 danpoong 리모트로
git push danpoong main
```

push 후 GitHub Actions 배포 완료까지 약 3~5분 소요. Cloud Run 로그에서 확인.

---

## 7. 🔒 보안 가이드라인

### 절대 금지 사항

> **코드, 설정 파일, 커밋 히스토리 어디에도 아래 정보를 직접 입력하지 않는다.**

- DB 비밀번호
- JWT 시크릿 키
- API Key (GCP, 11번가, 쿠팡 등 모든 외부 서비스)
- OAuth 클라이언트 시크릿

### 민감 정보 관리 원칙

| 환경 | 관리 방법 |
|------|-----------|
| 로컬 개발 | `backend/.env` 파일 (`.gitignore`에 반드시 포함) |
| CI/CD (GitHub Actions) | GitHub Secrets (`${{ secrets.SECRET_NAME }}`) |
| Cloud Run (프로덕션) | `--set-env-vars`로 Secrets 값 주입 (YAML에 값 하드코딩 금지) |

### .gitignore 필수 항목 확인

```
.env
.env.local
.env.production
*.pem
*.key
```

### 코드 리뷰 시 보안 체크

새 코드를 push하기 전, 아래 항목을 직접 점검:

- [ ] `grep -r "password" backend/` 실행 → `.env` 외 파일에 비밀번호 없는지 확인
- [ ] `grep -r "secret" backend/` 실행 → 하드코딩된 시크릿 없는지 확인
- [ ] `git diff HEAD` 에서 민감 정보 노출 여부 육안 검토

---

## 8. 🚀 배포 체크리스트

### 배포 전 필수 확인

**코드 품질:**
- [ ] `ruff check .` 오류 없음
- [ ] `mypy .` 타입 오류 없음

**DB 마이그레이션:**
- [ ] 모델(`model.py`) 변경 시 `alembic revision --autogenerate` 실행했는지 확인
- [ ] 생성된 마이그레이션 파일을 커밋에 포함했는지 확인
- [ ] 로컬에서 `alembic upgrade head` 정상 완료 확인

**환경변수:**
- [ ] 새로운 환경변수가 추가된 경우 GitHub Secrets에 등록했는지 확인
- [ ] `deploy-cloudrun.yml`의 `--set-env-vars`에 새 환경변수 추가했는지 확인

**보안:**
- [ ] 커밋에 민감 정보(비밀번호, API Key 등)가 포함되지 않았는지 확인

### GitHub Actions 워크플로우 검토 절차

`.github/workflows/deploy-cloudrun.yml` 수정 시 아래 항목 반드시 확인:

1. **Secrets 누락 체크:** `${{ secrets.XXX }}`로 참조한 모든 변수가 GitHub → Settings → Secrets and variables → Actions에 실제로 등록되어 있는지 확인
2. **마이그레이션 단계:** `alembic upgrade head` 스텝이 `Deploy to Cloud Run` 스텝보다 앞에 위치하는지 확인
3. **환경변수 일치:** 마이그레이션 단계와 Cloud Run 배포 단계의 환경변수 목록이 동일한지 확인

### 현재 필요한 GitHub Secrets 목록

GitHub → Settings → Secrets and variables → Actions에서 등록:

| Secret 이름 | 설명 |
|------------|------|
| `GCP_SA_KEY` | Google Cloud 서비스 계정 JSON 키 |
| `DB_WRITE_USER` | DB 쓰기 계정 사용자명 |
| `DB_WRITE_PASSWORD` | DB 쓰기 계정 비밀번호 |
| `DB_WRITE_HOST` | DB 쓰기 호스트 IP |
| `DB_READ_USER` | DB 읽기 계정 사용자명 |
| `DB_READ_PASSWORD` | DB 읽기 계정 비밀번호 |
| `DB_READ_HOST` | DB 읽기 호스트 IP |
| `JWT_SECRET_KEY` | JWT 서명 시크릿 키 |

---

## 9. 🗄️ DB 마이그레이션 관리

### 기본 원칙

- **모델(`model.py`) 변경 = 반드시 마이그레이션 파일 생성**
- 마이그레이션 파일은 코드와 함께 커밋 (누락 시 Cloud Run 기동 실패)
- CI/CD 파이프라인이 자동으로 `alembic upgrade head`를 실행함

### 마이그레이션 작업 순서

```bash
# 1. model.py에서 필드/테이블 변경
# 2. 마이그레이션 파일 자동 생성
cd backend
alembic revision --autogenerate -m "add_xxx_column_to_yyy_table"

# 3. 생성된 파일 검토 (alembic/versions/xxxx_*.py)
# 4. 로컬에서 적용 확인
alembic upgrade head

# 5. 커밋 (마이그레이션 파일 포함)
git add alembic/versions/
git commit -m "DB 마이그레이션: xxx 컬럼 추가"
```

### CI/CD 자동 마이그레이션

`deploy-cloudrun.yml`의 `Run DB Migrations` 스텝이 Docker 이미지 배포 전에 자동 실행됨:

```yaml
- name: Run DB Migrations
  run: |
    alembic upgrade head   # 이 라인이 반드시 존재해야 함
```

### 마이그레이션 롤백

```bash
# 한 단계 되돌리기
alembic downgrade -1

# 특정 리비전으로 되돌리기
alembic downgrade <revision_id>
```

---

## 10. ⚙️ Cloud Run 환경변수 관리

### 환경변수 변경 시 보고 절차

새로운 환경변수가 추가되거나 변경될 때:

1. 이 문서의 아래 목록을 업데이트
2. **사용자에게 직접 입력 요청:** 아래 GitHub Secrets 등록이 필요한 항목을 명시하여 보고
3. `deploy-cloudrun.yml`의 `--set-env-vars`에 해당 변수 추가

### 현재 Cloud Run 환경변수 목록

| 변수명 | 출처 | 설명 |
|--------|------|------|
| `ENVIRONMENT` | 고정값 `production` | 실행 환경 |
| `write_db_user` | `secrets.DB_WRITE_USER` | DB 쓰기 사용자명 |
| `write_db_password` | `secrets.DB_WRITE_PASSWORD` | DB 쓰기 비밀번호 |
| `write_db_host` | `secrets.DB_WRITE_HOST` | DB 쓰기 호스트 |
| `write_db_port` | 고정값 `5432` | DB 포트 |
| `write_db_name` | 고정값 `samba-wave` | DB 이름 |
| `read_db_user` | `secrets.DB_READ_USER` | DB 읽기 사용자명 |
| `read_db_password` | `secrets.DB_READ_PASSWORD` | DB 읽기 비밀번호 |
| `read_db_host` | `secrets.DB_READ_HOST` | DB 읽기 호스트 |
| `read_db_port` | 고정값 `5432` | DB 포트 |
| `read_db_name` | 고정값 `samba-wave` | DB 이름 |
| `db_ssl_required` | 고정값 `false` | SSL 비활성화 |
| `jwt_secret_key` | `secrets.JWT_SECRET_KEY` | JWT 서명 키 |
| `AWS_EC2_METADATA_DISABLED` | 고정값 `true` | AWS SDK 오작동 방지 |

### 로컬 `.env` 파일 구조 (backend/.env)

```env
environment=development

# 쓰기 DB
write_db_user=samba-user
write_db_password=<비밀번호>
write_db_host=<DB_HOST>
write_db_port=5432
write_db_name=samba-wave

# 읽기 DB
read_db_user=samba-user
read_db_password=<비밀번호>
read_db_host=<DB_HOST>
read_db_port=5432
read_db_name=samba-wave

# 기타
db_ssl_required=false
jwt_secret_key=<로컬용_시크릿>
AWS_EC2_METADATA_DISABLED=true
```

> **이 파일은 절대 Git에 커밋하지 않는다.** `.gitignore`에 포함 확인 필수.

---

## 11. 코드 작성 규칙

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
