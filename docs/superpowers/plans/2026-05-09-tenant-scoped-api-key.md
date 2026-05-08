# 확장앱 API 키 — 테넌트 분리 plan

## Context

현재 `backend/middleware/api_gateway.py` 는 단일 글로벌 키 (`settings.api_gateway_key`)
하나로 모든 확장앱 트래픽을 인증한다. `/api/v1/samba/sourcing-accounts/extension-key`
엔드포인트는 무인증으로 이 글로벌 키를 반환한다.

**위험:**
1. 키가 한번 유출되면 모든 테넌트의 데이터가 동일 위협에 노출
2. `/login-credential` 응답에 소싱처 평문 ID/PW 포함 → 키만 알면 누구나 조회 가능
3. 멀티테넌시 전환 시 테넌트 간 격리 불가 (현재 가장 큰 SaaS 전환 블로커)

**임시 보강 (2026-05-09 적용 完):** IP당 분당 10회 레이트리밋 + 비정상 호출 감사 로그
→ 부트포스 차단은 되지만 한 번이라도 새는 키는 글로벌 위험 그대로.

---

## 목표 상태

- 확장앱은 **테넌트별로 발급된** 키를 사용
- 키 발급은 **사용자 JWT 인증 후** 만 가능 (웹 로그인 → 확장앱 키 발급 → 저장)
- 키 회수(revoke), 만료(rotate) 가능
- 글로벌 키는 단계적으로 폐기

---

## 단계별 전환

### 단계 1 — 테이블 + 발급 엔드포인트 (additive)

**테이블:**
```sql
CREATE TABLE samba_extension_key (
    id VARCHAR(40) PRIMARY KEY,                  -- ulid
    key_hash VARCHAR(128) NOT NULL UNIQUE,       -- 키 평문 저장 금지, sha256 hash
    tenant_id VARCHAR(40),                       -- nullable (단일 사용자 환경 호환)
    user_id VARCHAR(40) NOT NULL,                -- 발급자
    label VARCHAR(80),                           -- 사용자 메모 (예: "회사 PC")
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);
CREATE INDEX ON samba_extension_key (tenant_id, revoked_at) WHERE revoked_at IS NULL;
```

**엔드포인트 (모두 JWT 필수):**
- `POST /api/v1/samba/extension-keys` — 새 키 발급 (응답에 평문 키 1회 노출, 이후 hash 만 저장)
- `GET /api/v1/samba/extension-keys` — 본인/테넌트 발급 키 목록
- `DELETE /api/v1/samba/extension-keys/{id}` — revoke

### 단계 2 — 미들웨어 dual-check

**`api_gateway.py` 수정:**
```python
# 1순위: 테넌트 키 (DB 조회, 캐시 1분)
# 2순위: 글로벌 키 (기존 동작 호환)
# 3순위: 차단 + 로그
```

캐시: `lru_cache` 또는 redis 1분 TTL — 모든 요청에 DB 쿼리 추가하지 않도록.
키 hit 시 `request.state.tenant_id` 주입 → 라우터에서 활용 가능.

### 단계 3 — 확장앱 발급 플로우

확장앱 popup:
1. 백엔드 URL 입력 (기존 동일)
2. **신규:** "웹사이트로 로그인" 버튼 → `https://samba-wave.vercel.app/extension-link?cb=...`
3. 웹페이지에서 사용자 로그인 → 키 발급 → `chrome.runtime.sendMessage(EXT_ID, {key})` 또는 deep link
4. 확장앱이 키를 `chrome.storage.local` 저장 → 이후 모든 호출에 X-Api-Key 로 사용

### 단계 4 — 글로벌 키 폐기

- 테넌트별 키 발급률 80% 이상 도달 시 (예: 1주일 후) 글로벌 키 검증을 환경변수 토글로 비활성
- 일정 기간 후 `_EXEMPT_PATHS` 에서 `/extension-key` 제거 (legacy 폴백 제거)
- 마지막으로 글로벌 키 회전 → 사실상 무효화

---

## 위험·고려사항

- **확장앱 강제 업데이트** 메커니즘 필요 — 단계 3 배포 시 기존 확장앱은 동작하나 신규 키 발급 못함
  - `minExtVersion` 활용 (이미 백엔드 응답에 추가 完, 2026-05-09)
- **자동 로그인 자격증명 (`/login-credential`)** 도 테넌트 스코프로 강제
  - 단계 1 즉시 적용 가능 (X-Api-Key 가 테넌트 키일 경우 해당 테넌트만 조회)
- **레거시 호환** — 글로벌 키와 테넌트 키 혼용 기간 동안 logger 에 키 종류 기록해 사용량 모니터링

---

## 진행 권장 시점

- 단계 1: 평일 (코드만, 운영 영향 최소)
- 단계 2: 평일 오전, 미들웨어 변경이라 신중 — 테넌트 키 미발급 상태 라도 글로벌 키 fallback 유지로 안전
- 단계 3: 사용자 안내·문서 동시 진행 (확장앱 popup UI 변경 동반)
- 단계 4: 단계 3 배포 1주 후 발급률 확인 후

**미들웨어 변경은 새벽·주말 진행 절대 금지 — 잘못되면 모든 확장앱 차단됨.**
