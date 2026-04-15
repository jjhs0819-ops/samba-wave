# CLAUDE-DEPLOY.md — Samba Wave 배포/보안/마이그레이션 참조

> 배포·보안·마이그레이션·환경변수 상세 규칙 문서. Claude Code 자동 로딩 대상 아님 — 필요할 때만 참조.

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
