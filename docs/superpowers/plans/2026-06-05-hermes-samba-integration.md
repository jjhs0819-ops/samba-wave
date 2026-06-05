# Hermes ↔ 삼바 통합 로드맵

작성일: 2026-06-05
브랜치: `claude/hermes-samba-integration-WVXtr`

맥미니에 띄운 로컬 LLM(**Hermes 3**, Ollama)을 삼바웨이브에 단계적으로 연결한다.
목표는 (1) 구글 Gemma 클라우드 비용·rate limit 절감, (2) 텔레그램 원격 제어,
(3) **주문처리 100% 자동화**.

> 비전/이미지 분류는 Hermes3(텍스트 전용)가 못 하므로 **Gemma 유지**. 전환 대상은
> 텍스트 생성 작업(정책·태그·SNS 글쓰기 등)뿐이다.

## 최종 목표 (North Star)

```
삼바에 신규 주문 인입
   → 원문(소싱처) 링크에서 자동 결제
   → 결제·주문정보를 삼바에 자동 입력
   → 주문처리 100% 자동화
```

## 토폴로지

- 🧠 **두뇌**: 맥미니의 Ollama (`127.0.0.1:11434`), 모델 `hermes3:8b`. 외부 비노출.
- 🏢 **삼바 백엔드**: GCP VM (Caddy → FastAPI → Cloud SQL). 맥미니와 다른 네트워크.
- 🌉 **다리**: 클라우드 백엔드가 맥미니 Hermes를 써야 할 때만 Tailscale 등 사설망으로 연결.
  텔레그램 봇처럼 맥미니 안에서 도는 작업은 `127.0.0.1`로 충분(다리 불필요).

접속 주소는 `OLLAMA_BASE_URL` 환경변수로 주입한다.
- 같은 머신: `http://127.0.0.1:11434` (기본값)
- 원격 맥미니(클라우드에서 호출): `http://<tailscale-ip>:11434`
  (이 경우 맥미니에서 `OLLAMA_HOST=0.0.0.0` 으로 Ollama를 tailnet 인터페이스에 바인딩)

## 단계 (Phase)

### Phase 0 — 두뇌 준비 ✅ 완료
- 맥미니에 공식 Ollama 앱(`brew install --cask ollama-app`, GPU/Metal 포함) 설치
- `ollama pull hermes3:8b`, 한국어 응답 확인

### Phase 1 — 텔레그램 AI 비서 (맥미니 로컬)
- 맥미니에서 도는 텔레그램 봇(폴링 방식 → 맥미니 외부 비노출, 안전)
- 기능: 대화/요약/번역/아이디어, 이미지·텍스트 정리, 정기 리포트 알림(스케줄)
- 두뇌 호출은 `127.0.0.1:11434` 로컬 → 다리 불필요

### Phase 2 — 삼바 텍스트 AI를 Hermes로 전환 (코드) ← 현재 토대 작업
- `backend/backend/domain/samba/ai/hermes_client.py` 추가 (gemma_client 호환 인터페이스)
- `settings.ai_text_provider` 토글(`gemma`|`hermes`)로 텍스트 생성 라우팅
- 대상 호출부: `policy.py`(태그/정책 생성), `sns_posting/ai_writer.py`(SNS 글쓰기) 등
- 기본값은 `gemma` 유지 → 즉시 롤백 가능, 점진 전환

### Phase 3 — 클라우드 ↔ 맥미니 다리 (Tailscale)
- 맥미니·GCP VM을 같은 tailnet에 가입, 맥미니 Ollama를 tailnet에 바인딩
- 클라우드 백엔드 `OLLAMA_BASE_URL=http://<macmini-tailscale-ip>:11434`
- Phase 2 토글을 `hermes`로 넘겨 클라우드 작업도 맥미니 두뇌 사용

### Phase 4 — 운영 원격 명령 (텔레그램)
- 텔레그램에서 주문/배송 조회, 반품·CS 답변 초안 생성 등 읽기/보조 명령
- 민감하지 않은(돈 안 나가는) 작업부터

### Phase 5 — 주문처리 자동화 (North Star) ⚠️ 최후·신중

**현황 (코드 조사 결과):** 파이프라인의 약 95%가 이미 자동화돼 있다.
- ✅ 자동: 주문 인입(8개 마켓 `order/poller.py`), `source_url`/`source_site` 저장,
  소싱처 **자동 로그인**(`extension/background-autologin.js`), 가격 수집
  (레시피 엔진 + `tools/lotteon_daemon/daemon.py` Playwright), 송장 수집,
  마켓 송장 전송(`send_invoice_to_market`).
- ❌ **유일한 빈칸 = 결제(장바구니→결제 클릭)** + 결제 후 `sourcing_order_number` 기록.

즉 "100% 자동화"의 실제 미션은 **자동 결제(checkout) 한 조각**이다.

**재사용할 기존 인프라:** 레시피 엔진(사이트별 단계 시퀀스), 데몬(Playwright 헤드리스),
job queue(`samba_sourcing_job`, 크래시 복원), `/proxy/sourcing/collect-result` 콜백.

**Hermes(두뇌)의 역할:** 결제 클릭 자체는 레시피/데몬이 수행. Hermes는 판단 보조 —
(a) **옵션 매칭**: 주문 옵션("270/블랙") ↔ 소싱처 옵션 셀렉터 연결(퍼지 매칭),
(b) 주문확인 페이지에서 `sourcing_order_number` 추출.

**안전 단계 (반드시 순차, 텔레그램 봇 = 승인 게이트):**
- 5a. (돈 X) 신규 주문 감지 → 텔레그램 알림 + Hermes 옵션 매칭 제안. 읽기 전용.
- 5b. (돈 X) **드라이런**: 로그인→장바구니→옵션선택→결제 직전까지 자동, 결제 버튼 직전 정지.
  텔레그램으로 "결제할까요? [예/아니오]" 승인 요청(금액·상품 표시).
- 5c. 승인 시 결제 실행 + 결과 페이지에서 `sourcing_order_number` 자동 추출 →
  `PUT /api/v1/samba/orders/{id}` 로 기록.
- 5d. 신뢰 누적 후 조건부(금액 한도·소싱처 화이트리스트·계정별) 전액 자동.
- 리스크: 소싱처 계정 잠금/봇 감지, 금액·옵션 오류, 환불/취소. 한도·전체 로깅·롤백 필수.

**핵심 파일(구현 시 진입점):**
- 주문: `backend/backend/domain/samba/order/{model,service,repository,poller}.py`,
  `backend/backend/api/v1/routers/samba/order.py`
- 소싱 계정/상품: `domain/samba/sourcing_account/model.py`, `domain/samba/product/model.py`
- 자동화 실행: `extension/background-sourcing.js`, `extension/recipe-executor.js`,
  `tools/lotteon_daemon/daemon.py`, `domain/samba/proxy/sourcing_queue.py`
- 결제 기록 필드: `SambaOrder.sourcing_order_number`, `.sourcing_account_id`

## 비고
- 이 토대 커밋은 기존 Gemma 경로를 바꾸지 않는다(추가만). 토글 기본 `gemma`.
- 각 Phase는 독립적으로 가치가 나오며, 앞에서부터 순차 진행한다.
