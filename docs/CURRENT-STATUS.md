# 삼바웨이브 현재 상태 (2026-03-24)

> 신규 팀원이 프로젝트에 합류할 때 읽는 문서

---

## 서비스 개요

**삼바웨이브**는 무재고 위탁판매(드롭쉬핑) 관리 솔루션이다.

```
소싱처에서 상품 수집 → AI 가공 → 정책 적용 → 마켓에 등록 → 주문 관리
```

### 비즈니스 흐름

```
1. 상품수집    소싱처(무신사 등)에서 상품 정보를 긁어온다
2. 상품관리    수집된 상품을 편집 (이미지, 상품명, 옵션)
3. 정책생성    마진율, 배송비, 수수료 등 가격 정책을 만든다
4. 정책적용    상품에 정책을 연결한다
5. 카테고리    소싱처 카테고리 → 마켓 카테고리 매핑
6. 마켓전송    스마트스토어/쿠팡 등에 상품을 등록한다
7. 주문관리    마켓에서 들어온 주문을 수집/처리한다
8. CS관리     취소/반품/교환 처리
```

---

## 기술 스택

### 백엔드
- Python 3.12, FastAPI
- PostgreSQL (Railway, 싱가폴)
- SQLAlchemy + SQLModel (ORM)
- 비동기 (async/await)

### 프론트엔드
- Next.js 15, React 19, TypeScript
- Tailwind CSS 4
- Vercel 배포

### 크롬 확장앱
- 소싱처 웹페이지에서 상품 정보를 DOM으로 읽어서 서버에 전송
- 확장앱은 로직 없이 DOM 읽기 + 서버 전송만 (얇은 클라이언트)

---

## 주요 파일 구조

### 백엔드
```
backend/
  backend/
    api/v1/routers/samba/
      collector.py      수집 API (3035줄) ← 리팩토링 대상
      shipment.py       전송 API
      product.py        상품 CRUD API
      order.py          주문 API
      category.py       카테고리 API
    domain/samba/
      collector/        수집 서비스, 모델
      shipment/         전송 서비스, 디스패처
      proxy/            마켓 API 클라이언트 (스마트스토어, 쿠팡 등)
      policy/           정책 모델, 서비스
      order/            주문 모델, 서비스
      account/          마켓 계정 관리
```

### 프론트엔드
```
frontend/src/app/samba/
  collector/page.tsx    수집 페이지
  products/page.tsx     상품관리 (3147줄) ← 리팩토링 대상
  policies/page.tsx     정책관리
  categories/page.tsx   카테고리 매핑
  shipments/page.tsx    마켓전송
  orders/page.tsx       주문관리
  settings/page.tsx     설정
```

---

## 현재 지원 소싱처

| 소싱처 | 실사용 | 수집 방식 |
|--------|--------|----------|
| 무신사 (MUSINSA) | O | API + 상세페이지 크롤링 |
| 크림 (KREAM) | 부분 | API |
| 기타 9개 | X (UI만) | 미구현 |

## 현재 지원 마켓

| 마켓 | 상품등록 | 주문수집 | 비고 |
|------|---------|---------|------|
| 스마트스토어 | O | O | 메인 마켓 |
| 쿠팡 | O | O | |
| 11번가 | O | 부분 | |
| SSG | O | X | 계약 브랜드만 |
| 롯데ON | O | X | |
| 토스 | 부분 | X | 신규 |
| 라쿠텐 | 부분 | X | 해외 |
| 아마존 | 부분 | X | 해외 |
| 바이마 | 부분 | X | 해외 |

---

## 실행 방법

### 백엔드
```bash
cd backend
.venv/Scripts/python.exe run.py
# 포트: 28080
```

### 프론트엔드
```bash
cd frontend
pnpm dev
# 포트: 3000
```

### 주의사항
- uvicorn 직접 호출 금지 → `run.py` 사용
- 프론트/백 `.env` 파일 필요 (리드에게 받을 것)
- 확장앱 수정 시 반드시 버전 업데이트
- git push는 리드 승인 후에만
