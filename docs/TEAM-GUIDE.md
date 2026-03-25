# 팀 개발 가이드

> 5명이 충돌 없이 병렬 개발하기 위한 규칙

---

## 팀 역할

| 역할 | 담당 영역 | 작업 폴더 |
|------|----------|----------|
| A. 소싱 엔진 | 소싱처 플러그인 | `plugins/sourcing/`, `proxy/` |
| B. 마켓 엔진 | 판매처 플러그인 | `plugins/market/`, `proxy/` |
| C. 프론트엔드 | 상품/전송/주문 UI | `frontend/src/app/samba/` |
| D. 인프라 | DB, 캐시, 큐, 배포 | `backend/db/`, `docker/`, `.github/` |
| E. 리드 | 핵심 로직, 리뷰 | `domain/samba/shipment/`, `domain/samba/collector/` |

---

## Git 브랜치 전략

```
main                          ← 배포 (보호, 직접 푸시 금지)
  ├── feature/sourcing-olive  ← A가 올리브영 플러그인 개발
  ├── feature/market-ssg      ← B가 SSG 마켓 플러그인 개발
  ├── feature/virtual-scroll  ← C가 가상 스크롤 개발
  ├── feature/redis-cache     ← D가 Redis 캐시 구축
  └── fix/price-calc          ← E가 가격 계산 버그 수정
```

### 규칙
- 브랜치명: `feature/기능명` 또는 `fix/버그명`
- 커밋 메시지: 한국어
- PR 머지: 최소 1명 리뷰 후 머지
- main 직접 푸시: 절대 금지

---

## PR (Pull Request) 규칙

### PR 작성 시

```markdown
## 변경 사항
- 올리브영 소싱 플러그인 추가

## 테스트
- [ ] 키워드 검색 동작 확인
- [ ] 상품 상세 수집 확인
- [ ] 품절 상품 필터링 확인

## 영향 범위
- 새 파일 추가만, 기존 코드 수정 없음
```

### 리뷰어 규칙

- 소싱 플러그인 PR → 리드(E) 리뷰
- 마켓 플러그인 PR → 리드(E) 리뷰
- 프론트 PR → 리드(E) 또는 D 리뷰
- 인프라 PR → 리드(E) 리뷰

---

## 코드 규칙

### 공통
- 파일당 최대 **500줄** (넘으면 분리)
- 함수당 최대 **50줄** (넘으면 분리)
- 주석은 한국어
- 변수/함수명은 영어

### 프론트엔드 (TypeScript)
- 들여쓰기: 스페이스 2칸
- 세미콜론: 사용하지 않음
- 따옴표: 작은따옴표
- 컴포넌트: PascalCase
- 변수/함수: camelCase
- any 타입: 사용 금지

### 백엔드 (Python)
- 함수/변수: snake_case
- 클래스: PascalCase
- 포매터: black
- 린터: ruff
- 타입 힌트: 필수

---

## 폴더 소유권

> 각 팀원은 자기 폴더만 수정. 다른 폴더 수정 시 PR에 해당 담당자를 리뷰어로 지정

```
backend/
  domain/samba/
    plugins/
      sourcing/     ← A 소유
      market/       ← B 소유
    collector/      ← E 소유 (A 협업)
    shipment/       ← E 소유 (B 협업)
    policy/         ← E 소유
    order/          ← B 소유
  db/               ← D 소유

frontend/
  src/app/samba/    ← C 소유
  src/lib/samba/    ← C 소유 (E 협업)
```

---

## 일일 루틴

### 매일 아침 (10분)
1. `git pull origin main` — 최신 코드 받기
2. 내 브랜치에 main 머지 — `git merge main`
3. 충돌 있으면 즉시 해결

### 매일 저녁
1. 작업 커밋 + 푸시
2. 완료된 기능은 PR 생성

### 주 1회 (금요일)
1. 전체 팀 미팅 (30분)
2. 각자 진행 상황 공유
3. 다음 주 목표 설정
4. 블로커 논의

---

## 커뮤니케이션

- **급한 것**: 슬랙/카톡 DM
- **PR 리뷰 요청**: GitHub PR 코멘트
- **설계 논의**: GitHub Issue 또는 미팅
- **버그 리포트**: GitHub Issue (재현 방법 필수)
