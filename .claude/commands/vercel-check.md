# Vercel 빌드 검수

푸시 전에 Vercel 배포가 실패하지 않도록 프론트엔드 코드를 검수한다.

## 실행 순서

### 1단계: TypeScript 컴파일 체크
```bash
cd frontend && npx tsc --noEmit 2>&1
```
- 에러가 있으면 **모두 수정**한 뒤 다시 체크
- 주요 패턴: 타입 불일치, 미사용 import, 누락된 속성

### 2단계: Next.js 프로덕션 빌드
```bash
cd frontend && pnpm build 2>&1
```
- `next build`가 성공해야 Vercel 배포가 성공함
- 에러가 있으면 **모두 수정**한 뒤 다시 빌드
- 주요 패턴:
  - `Module not found` — import 경로 오류
  - `Type error` — tsc에서 안 잡히는 빌드 시점 타입 에러
  - `Image Optimization` — next/image 설정 문제
  - `Dynamic server usage` — 서버 컴포넌트에서 클라이언트 API 사용

### 3단계: 결과 보고
- 모든 체크 통과 시: "Vercel 빌드 검수 통과 — 푸시 가능합니다"
- 수정한 파일이 있으면: 수정 내역 요약 후 "수정 완료 — 다시 검수합니다" → 1단계부터 재실행
- 3회 반복해도 해결 안 되는 에러: 에러 내용 보고 후 사용자에게 판단 요청

## 자주 발생하는 Vercel 빌드 에러

### Next.js 15 / React 19 관련
- `useRef<T>(null)` → `useRef<T | null>(null)` (React 19 strict)
- `params`가 Promise로 변경됨 → `await params` 필요
- `searchParams`도 동일

### ESLint 관련
- `@typescript-eslint/no-unused-vars` — 미사용 변수/import 제거
- `react-hooks/exhaustive-deps` — useEffect 의존성 누락
- `@next/next/no-img-element` — img 태그 대신 next/image 사용

### 빌드 최적화
- 번들 사이즈 경고 시 동적 import(`next/dynamic`) 검토
- `'use client'` 누락으로 서버 컴포넌트에서 useState/useEffect 사용
