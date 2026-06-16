#!/usr/bin/env python3
"""맥미니 Hermes 비서 봇 (Phase 4) — 삼바 주문 데이터 연결.

의존성 0 (표준 라이브러리만). `python3 telegram_brain_bot.py` 로 바로 실행.

환경변수:
  TELEGRAM_BOT_TOKEN        (필수) @BotFather 토큰
  TELEGRAM_ALLOWED_USER_IDS (권장) 콤마 구분 숫자 — 비우면 누구나 사용
  OLLAMA_BASE_URL           (선택) 기본 http://127.0.0.1:11434
  HERMES_MODEL              (선택) 기본 hermes3:8b

  SAMBA_BACKEND_URL         (선택) 기본 http://127.0.0.1:28080
  SAMBA_EMAIL               (필수, 삼바 기능) 삼바 로그인 이메일
  SAMBA_PASSWORD            (필수, 삼바 기능) 삼바 로그인 비밀번호
  SAMBA_API_KEY             (운영 필수) X-Api-Key. 프론트 NEXT_PUBLIC_API_GATEWAY_KEY 와 동일.
                            운영 백엔드는 이 헤더 없으면 삼바 API 403 차단.
  NEW_ORDER_POLL_MINUTES    (선택) 신규 미발주 감지 주기(분), 기본 10
  DAILY_REPORT_HOUR         (선택) 아침 자동 다이제스트 시각(KST 0~23), 기본 9. 비우면 끔.

명령:
  /오늘     — 오늘 주문 현황 요약
  /미발주   — 발주 필요한 주문 목록 (최근 7일)
  /매출     — 오늘 + 이달 누계 매출·이익·마진 + 베스트셀러
  /주문현황 — 상태별 건수 + 미발송 + 전월대비
  /CS       — 미답변/답변완료 + 마켓별·유형별 분포
  /반품     — 반품 상태별·유형별·사유별 + 승인대기
  /도움말   — 전체 명령어 안내
  /reset    — 대화 기억 초기화
  /whoami   — 내 텔레그램 user id
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

# ── 텔레그램 설정 ──────────────────────────────────────────────────────────
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED = {
    s.strip()
    for s in os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").split(",")
    if s.strip()
}
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
HERMES_MODEL = os.environ.get("HERMES_MODEL", "hermes3:8b")

# ── 삼바 백엔드 설정 ────────────────────────────────────────────────────────
SAMBA_URL = os.environ.get("SAMBA_BACKEND_URL", "http://127.0.0.1:28080").rstrip("/")
SAMBA_EMAIL = os.environ.get("SAMBA_EMAIL", "")
SAMBA_PASSWORD = os.environ.get("SAMBA_PASSWORD", "")
# API 게이트웨이 키(X-Api-Key). 프론트의 NEXT_PUBLIC_API_GATEWAY_KEY 와 동일한 공개 키.
# 운영 백엔드는 이 헤더가 없으면 삼바 API를 403 차단함.
SAMBA_API_KEY = os.environ.get("SAMBA_API_KEY", "")
NEW_ORDER_POLL_MINUTES = int(os.environ.get("NEW_ORDER_POLL_MINUTES", "10"))
# 아침 자동 다이제스트 발송 시각(KST, 0~23). 빈 값이면 자동보고 비활성화.
DAILY_REPORT_HOUR = os.environ.get("DAILY_REPORT_HOUR", "9").strip()

TG_API = f"https://api.telegram.org/bot{TOKEN}"
KST = timezone(timedelta(hours=9))

# ── 대화 기억 ──────────────────────────────────────────────────────────────
_HISTORY: dict[int, list[dict[str, str]]] = {}
_MAX_TURNS = 12

SYSTEM_PROMPT = (
    "You are a personal assistant. "
    "CRITICAL RULE: Always respond in Korean ONLY. Never mix in ANY words from other languages. "
    "너는 한국어로만 답하는 개인 비서야. 반드시 순수한 한국어로만 답해. "
    "러시아어·베트남어·영어 등 외국어 단어를 절대 섞지 마. "
    "요약·번역·아이디어·정리를 잘 돕고, 모르면 모른다고 솔직히 말해."
)


# ══════════════════════════════════════════════════════════════════════════
# HTTP 유틸
# ══════════════════════════════════════════════════════════════════════════

def _http_json(url: str, payload: dict | None = None,
               headers: dict | None = None, timeout: float = 60.0) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    h = {"Content-Type": "application/json"} if data else {}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get(url: str, params: dict | None = None,
              headers: dict | None = None, timeout: float = 30.0) -> dict:
    if params:
        import urllib.parse
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{url}?{query}"
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ══════════════════════════════════════════════════════════════════════════
# 삼바 클라이언트
# ══════════════════════════════════════════════════════════════════════════

class SambaClient:
    def __init__(self) -> None:
        self._token: str | None = None
        self._token_expiry: float = 0.0
        self._lock = threading.Lock()

    @property
    def is_ready(self) -> bool:
        return bool(SAMBA_EMAIL and SAMBA_PASSWORD)

    def _login(self) -> bool:
        try:
            # 삼바 사용자 로그인 — samba_user 테이블 기반. JWT는 access_token 필드로 반환.
            # (구 /auth/email/login 은 user 테이블 기반이라 이 SaaS 에선 미작동)
            resp = _http_json(
                f"{SAMBA_URL}/api/v1/samba/users/login",
                {"email": SAMBA_EMAIL, "password": SAMBA_PASSWORD},
                timeout=15,
            )
            self._token = resp.get("access_token")
            # 29일 후 만료로 설정 (실제 30일, 여유 1일)
            self._token_expiry = time.time() + 60 * 60 * 24 * 29
            print(f"[삼바] 로그인 성공 (닉네임: {resp.get('nickname', SAMBA_EMAIL)})")
            return True
        except Exception as e:
            print(f"[삼바] 로그인 실패: {e}", file=sys.stderr)
            self._token = None
            return False

    def _ensure_token(self) -> str | None:
        with self._lock:
            if not self._token or time.time() > self._token_expiry:
                self._login()
            return self._token

    def _auth_headers(self) -> dict:
        token = self._ensure_token()
        headers: dict = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if SAMBA_API_KEY:  # 운영 API 게이트웨이 통과용 (없으면 403)
            headers["X-Api-Key"] = SAMBA_API_KEY
        return headers

    def _get_orders_paged(self, start_kst: str, end_kst: str, limit: int = 500) -> dict | None:
        try:
            return _http_get(
                f"{SAMBA_URL}/api/v1/samba/orders/by-date-range-paged",
                params={"start": start_kst, "end": end_kst,
                        "limit": str(limit), "sort_by": "date_desc"},
                headers=self._auth_headers(),
                timeout=20,
            )
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self._token = None  # 강제 재로그인 트리거
            print(f"[삼바] 주문 조회 실패: {e}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"[삼바] 주문 조회 실패: {e}", file=sys.stderr)
            return None

    def get_today_summary(self) -> dict | None:
        """오늘(KST) 주문 요약."""
        if not self.is_ready:
            return None
        today = datetime.now(KST).strftime("%Y-%m-%d")
        return self._get_orders_paged(today, today)

    def get_unplaced_orders(self) -> list[dict]:
        """최근 7일 중 sourcing_order_number 없는 주문 (발주 필요)."""
        if not self.is_ready:
            return []
        end = datetime.now(KST).strftime("%Y-%m-%d")
        start = (datetime.now(KST) - timedelta(days=7)).strftime("%Y-%m-%d")
        resp = self._get_orders_paged(start, end)
        if not resp:
            return []
        orders = resp.get("items", [])
        cancelled_statuses = {"cancelled", "cancel_requested", "returned", "return_requested"}
        return [
            o for o in orders
            if not (o.get("sourcing_order_number") or "").strip()
            and o.get("status") not in cancelled_statuses
        ]

    def get_newest_unplaced_order(self, prefer_site: str = "MUSINSA") -> dict | None:
        """가장 최근 미발주 주문 1건. 가능하면 prefer_site(무신사) 우선."""
        orders = self.get_unplaced_orders()
        if not orders:
            return None
        orders.sort(
            key=lambda o: (o.get("paid_at") or o.get("created_at") or ""),
            reverse=True,
        )
        preferred = [o for o in orders if (o.get("source_site") or "").upper() == prefer_site.upper()]
        return (preferred or orders)[0]

    # ── 보고용 범용 GET (401 시 1회 재로그인 후 재시도) ──────────────────────
    def _get(self, path: str, params: dict | None = None):
        """삼바 백엔드 GET. 성공 시 dict/list, 실패 시 None."""
        if not self.is_ready:
            return None
        url = f"{SAMBA_URL}{path}"
        for attempt in range(2):
            try:
                return _http_get(url, params=params,
                                 headers=self._auth_headers(), timeout=20)
            except urllib.error.HTTPError as e:
                if e.code == 401 and attempt == 0:
                    self._token = None  # 강제 재로그인 후 1회 재시도
                    continue
                print(f"[삼바] GET {path} 실패: {e}", file=sys.stderr)
                return None
            except Exception as e:
                print(f"[삼바] GET {path} 실패: {e}", file=sys.stderr)
                return None
        return None

    # 보고 영역별 호출 (경로/파라미터는 백엔드 라우터 본문 기준)
    def analytics_range(self, start: str, end: str) -> dict | None:
        return self._get("/api/v1/samba/analytics/range",
                         {"start_date": start, "end_date": end})

    def order_dashboard(self) -> dict | None:
        return self._get("/api/v1/samba/orders/dashboard-stats")

    def order_status_stats(self) -> dict | None:
        return self._get("/api/v1/samba/analytics/order-status")

    def best_sellers(self, days: int = 30, limit: int = 3) -> list | None:
        return self._get("/api/v1/samba/analytics/best-sellers",
                         {"days": str(days), "limit": str(limit)})

    def cs_stats(self) -> dict | None:
        return self._get("/api/v1/samba/cs-inquiries/stats")

    def return_stats(self) -> dict | None:
        return self._get("/api/v1/samba/returns/stats")


samba = SambaClient()


# ══════════════════════════════════════════════════════════════════════════
# 텔레그램 전송
# ══════════════════════════════════════════════════════════════════════════

def tg_send(chat_id: int, text: str) -> None:
    for i in range(0, max(len(text), 1), 4000):
        chunk = text[i:i + 4000] or "(빈 응답)"
        try:
            _http_json(f"{TG_API}/sendMessage",
                       {"chat_id": chat_id, "text": chunk}, timeout=30)
        except urllib.error.URLError as e:
            print(f"[경고] 메시지 전송 실패: {e}", file=sys.stderr)


# ══════════════════════════════════════════════════════════════════════════
# Hermes 두뇌
# ══════════════════════════════════════════════════════════════════════════

def ask_hermes_oneshot(prompt: str) -> str:
    """대화 기억을 건드리지 않는 1회성 질문 (옵션매칭 등 분석용)."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}]
    try:
        data = _http_json(
            f"{OLLAMA_BASE_URL}/api/chat",
            {"model": HERMES_MODEL, "messages": messages, "stream": False},
            timeout=180,
        )
        return str(data.get("message", {}).get("content", "")).strip() or "(분석 실패)"
    except Exception as e:
        return f"(헤르메스 분석 실패: {e})"


def ask_hermes(chat_id: int, user_text: str) -> str:
    history = _HISTORY.setdefault(chat_id, [])
    history.append({"role": "user", "content": user_text})
    if len(history) > _MAX_TURNS:
        del history[:-_MAX_TURNS]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history]
    try:
        data = _http_json(
            f"{OLLAMA_BASE_URL}/api/chat",
            {"model": HERMES_MODEL, "messages": messages, "stream": False},
            timeout=180,
        )
        answer = str(data.get("message", {}).get("content", "")).strip()
    except urllib.error.URLError as e:
        return f"⚠️ 두뇌(Ollama) 호출 실패: {e}\nOllama가 켜져 있는지 확인해줘."
    except Exception as e:
        return f"⚠️ 오류: {e}"
    if not answer:
        return "(두뇌가 빈 응답을 줬어. 다시 시도해줘.)"
    history.append({"role": "assistant", "content": answer})
    return answer


# ══════════════════════════════════════════════════════════════════════════
# 삼바 명령 포맷터
# ══════════════════════════════════════════════════════════════════════════

def _fmt_price(v) -> str:
    try:
        return f"₩{int(float(v or 0)):,}"
    except Exception:
        return "₩?"


def cmd_today(chat_id: int) -> None:
    if not samba.is_ready:
        tg_send(chat_id, "⚠️ SAMBA_EMAIL / SAMBA_PASSWORD 환경변수가 없어.\n삼바 연결 설정이 필요해.")
        return
    tg_send(chat_id, "📊 오늘 주문 조회 중...")
    result = samba.get_today_summary()
    if result is None:
        tg_send(chat_id, "❌ 삼바 서버 연결 실패.\n백엔드가 켜져 있는지 확인해줘.")
        return

    items = result.get("items", [])
    total = result.get("total_count", len(items))
    total_sale = result.get("total_sale") or sum(float(o.get("sale_price") or 0) for o in items)
    total_profit = sum(float(o.get("profit") or 0) for o in items)

    cancelled = {"cancelled", "cancel_requested", "returned", "return_requested"}
    active = [o for o in items if o.get("status") not in cancelled]
    unplaced = [o for o in active if not (o.get("sourcing_order_number") or "").strip()]
    shipped = [o for o in items if (o.get("tracking_number") or "").strip()]
    cancelled_orders = [o for o in items if o.get("status") in cancelled]

    today_str = datetime.now(KST).strftime("%Y년 %m월 %d일")
    lines = [
        f"📦 오늘 주문 현황 ({today_str})",
        "",
        f"전체: {total}건",
        f"매출: {_fmt_price(total_sale)}",
        f"이익: {_fmt_price(total_profit)}",
        "",
    ]
    if unplaced:
        lines.append(f"⏳ 미발주(발주 필요): {len(unplaced)}건  ← 처리 필요!")
    else:
        lines.append("✅ 미발주 없음 (모두 발주 완료)")
    lines.append(f"🚚 송장 입력 완료: {len(shipped)}건")
    lines.append(f"❌ 취소/반품: {len(cancelled_orders)}건")
    if unplaced:
        lines += ["", "/미발주 — 발주 필요 목록 보기"]
    tg_send(chat_id, "\n".join(lines))


def cmd_unplaced(chat_id: int) -> None:
    if not samba.is_ready:
        tg_send(chat_id, "⚠️ SAMBA_EMAIL / SAMBA_PASSWORD 환경변수가 없어.")
        return
    tg_send(chat_id, "🔍 미발주 주문 조회 중 (최근 7일)...")
    orders = samba.get_unplaced_orders()

    if not orders:
        tg_send(chat_id, "✅ 미발주 주문이 없어! 모두 발주 완료야.")
        return

    lines = [f"⏳ 미발주 주문 {len(orders)}건 (최근 7일 기준)"]
    for i, o in enumerate(orders[:20], 1):
        paid_at = (o.get("paid_at") or "")[:10] or "날짜미상"
        channel = o.get("channel_name") or "?"
        product = (o.get("product_name") or "상품명없음")[:30]
        option = o.get("product_option") or ""
        source_site = o.get("source_site") or "소싱처미상"
        sale_price = _fmt_price(o.get("sale_price"))
        source_url = (o.get("source_url") or "").strip()

        lines.append("")
        lines.append(f"{i}. [{channel}] {product}")
        if option:
            lines.append(f"   옵션: {option}")
        lines.append(f"   소싱처: {source_site}  판매가: {sale_price}  ({paid_at})")
        if source_url:
            lines.append(f"   🔗 {source_url}")

    if len(orders) > 20:
        lines.append(f"\n... 외 {len(orders) - 20}건 더 있음")
    tg_send(chat_id, "\n".join(lines))


def cmd_process(chat_id: int) -> None:
    """5a: 최신 미발주 주문을 분석하고 발주 준비 카드를 만든다 (결제 없음)."""
    if not samba.is_ready:
        tg_send(chat_id, "⚠️ SAMBA_EMAIL / SAMBA_PASSWORD 환경변수가 없어.")
        return
    tg_send(chat_id, "🔍 최신 미발주 주문 분석 중...")
    order = samba.get_newest_unplaced_order()
    if not order:
        tg_send(chat_id, "✅ 처리할 미발주 주문이 없어! 모두 발주 완료야.")
        return

    channel = order.get("channel_name") or "?"
    product = order.get("product_name") or "상품명없음"
    option = (order.get("product_option") or "").strip() or "(옵션 정보 없음)"
    qty = order.get("quantity") or 1
    source_site = order.get("source_site") or "소싱처미상"
    source_url = (order.get("source_url") or "").strip()
    sale_price = _fmt_price(order.get("sale_price"))
    cost = _fmt_price(order.get("cost"))

    # 헤르메스 옵션매칭 제안 (1회성)
    prompt = (
        f"우리 쇼핑몰 고객 주문을 소싱처({source_site})에서 대신 구매하려고 해. "
        f"고객이 고른 옵션을 소싱처에서 어떻게 선택해야 하는지 정리해줘.\n\n"
        f"상품명: {product}\n"
        f"고객 선택 옵션: {option}\n"
        f"수량: {qty}\n\n"
        f"아래 형식으로 한국어로만 간결하게 답해:\n"
        f"• 색상: (있으면)\n"
        f"• 사이즈: (있으면)\n"
        f"• 기타 옵션: (있으면)\n"
        f"• 주의: (옵션이 애매하거나 확인 필요하면 적기, 없으면 '없음')"
    )
    suggestion = ask_hermes_oneshot(prompt)

    lines = [
        "📋 발주 준비 카드 (5a — 결제 전 단계)",
        "",
        f"🛒 마켓: {channel}",
        f"📦 상품: {product}",
        f"🎨 고객 옵션: {option}",
        f"🔢 수량: {qty}",
        f"💰 판매가: {sale_price}  (원가: {cost})",
        f"🏬 소싱처: {source_site}",
    ]
    if source_url:
        lines.append(f"🔗 원문: {source_url}")
    lines += [
        "",
        "🧠 헤르메스 옵션매칭 제안:",
        suggestion,
        "",
        "─────────────",
        "위 정보로 무신사에서 직접 발주하면 돼.",
        "(다음 단계 5b에서 장바구니~결제 직전까지 자동화 예정)",
    ]
    tg_send(chat_id, "\n".join(lines))


# ══════════════════════════════════════════════════════════════════════════
# 보고 명령 — 매출 / 주문현황 / CS / 반품
# ══════════════════════════════════════════════════════════════════════════

# 주문 상태 코드 → 한글 표시
_ORDER_STATUS_LABELS = {
    "pending": "접수/대기", "wait_ship": "발송대기", "processing": "처리중",
    "arrived": "입고", "ship_failed": "발송실패", "shipping": "배송중",
    "shipped": "발송완료", "delivered": "배송완료",
    "cancelled": "취소", "cancel_requested": "취소요청",
    "returned": "반품", "return_requested": "반품요청",
    "exchanged": "교환완료", "exchanging": "교환중", "exchange_requested": "교환요청",
}
_RETURN_STATUS_LABELS = {
    "requested": "요청", "approved": "승인", "completed": "완료",
    "rejected": "거부", "cancelled": "취소",
}
_CLAIM_TYPE_LABELS = {"cancel": "취소", "return": "반품", "exchange": "교환"}
_CS_TYPE_LABELS = {
    "product_question": "상품문의", "delivery": "배송", "exchange_return": "교환/반품",
    "general": "일반", "urgent_inquiry": "긴급", "claim": "클레임",
}


def _kst_date(offset_days: int = 0) -> str:
    return (datetime.now(KST) + timedelta(days=offset_days)).strftime("%Y-%m-%d")


def hermes_comment(area: str, facts: str) -> str:
    """수치 요약을 받아 한 줄짜리 한국어 인사이트를 생성. 실패 시 빈 문자열."""
    if not facts.strip():
        return ""
    prompt = (
        f"다음은 우리 쇼핑몰의 '{area}' 지표야. 딱 한 문장(40자 이내)으로 "
        f"가장 눈에 띄는 포인트나 해야 할 일을 한국어로만 짚어줘. "
        f"인사말·수식어 없이 핵심만. 특이사항 없으면 '특이사항 없음'.\n\n{facts}"
    )
    try:
        line = ask_hermes_oneshot(prompt).strip().split("\n")[0]
        return line[:80]
    except Exception:
        return ""


def _append_comment(lines: list[str], area: str) -> None:
    facts = "; ".join(s.strip() for s in lines if s.strip())[:600]
    c = hermes_comment(area, facts)
    if c:
        lines += ["", f"🧠 {c}"]


def build_sales_text(with_comment: bool = True) -> str:
    """오늘 + 이달 누계 매출/이익/마진 + 베스트셀러."""
    today, tomorrow = _kst_date(), _kst_date(1)
    month_first = datetime.now(KST).strftime("%Y-%m-01")

    day = samba.analytics_range(today, tomorrow)
    month = samba.analytics_range(month_first, tomorrow)
    dash = samba.order_dashboard()
    if day is None and month is None and dash is None:
        return "❌ 삼바 서버 연결 실패 (매출)."

    lines = [f"💰 매출 보고 ({datetime.now(KST).strftime('%m월 %d일')})", ""]
    if day:
        lines += [
            "▪️ 오늘",
            f"  매출 {_fmt_price(day.get('total_sales'))} · 주문 {int(day.get('total_orders') or 0)}건",
            f"  이익 {_fmt_price(day.get('total_profit'))} · 마진 {float(day.get('profit_rate') or 0):.1f}% · 객단가 {_fmt_price(day.get('avg_order_value'))}",
        ]
    if month:
        lines += [
            "",
            "▪️ 이달 누계",
            f"  매출 {_fmt_price(month.get('total_sales'))} · 주문 {int(month.get('total_orders') or 0)}건",
            f"  이익 {_fmt_price(month.get('total_profit'))} · 마진 {float(month.get('profit_rate') or 0):.1f}%",
        ]
    if isinstance(dash, dict):
        change = dash.get("salesChange")
        tm = dash.get("thisMonth") or {}
        if change is not None:
            arrow = "▲" if change > 0 else ("▼" if change < 0 else "—")
            lines.append(f"  전월대비 {arrow}{abs(change)}% · 이행률 {tm.get('fulfillment', 0)}%")

    best = samba.best_sellers(days=30, limit=3)
    if best:
        lines += ["", "🏆 베스트셀러 (최근 30일)"]
        for i, p in enumerate(best, 1):
            name = (p.get("product_name") or "?")[:24]
            lines.append(f"  {i}. {name} · {_fmt_price(p.get('sales'))} ({int(p.get('units') or 0)}개)")

    if with_comment:
        _append_comment(lines, "매출")
    return "\n".join(lines)


def build_order_status_text(with_comment: bool = True) -> str:
    """이달 처리량 + 상태별 건수."""
    dash = samba.order_dashboard()
    status = samba.order_status_stats()
    if dash is None and status is None:
        return "❌ 삼바 서버 연결 실패 (주문현황)."

    lines = ["📦 주문 처리 현황", ""]
    if isinstance(dash, dict):
        tm = dash.get("thisMonth") or {}
        lines += [
            "▪️ 이달",
            f"  주문 {int(tm.get('count') or 0)}건 · 매출 {_fmt_price(tm.get('sales'))}",
            f"  이행완료 {int(tm.get('fulfillmentCount') or 0)}건 ({tm.get('fulfillment', 0)}%)",
        ]
    if isinstance(status, dict) and status:
        lines += ["", "▪️ 상태별 (전체 누적)"]
        shown: set[str] = set()
        for key, label in _ORDER_STATUS_LABELS.items():
            if status.get(key):
                lines.append(f"  {label}: {int(status[key])}건")
                shown.add(key)
        for key, val in status.items():
            if key not in shown and val:
                lines.append(f"  {key}: {int(val)}건")

    if with_comment:
        _append_comment(lines, "주문 처리")
    return "\n".join(lines)


def build_cs_text(with_comment: bool = True) -> str:
    """CS 미답변/답변완료 + 유형/마켓 분포."""
    st = samba.cs_stats()
    if st is None:
        return "❌ 삼바 서버 연결 실패 (CS)."

    total = int(st.get("total") or 0)
    pending = int(st.get("pending") or 0)
    replied = int(st.get("replied") or 0)
    lines = [
        "💬 CS 현황", "",
        f"전체 {total}건 · ⏳미답변 {pending}건 · ✅답변완료 {replied}건",
    ]
    by_type = st.get("by_type") or {}
    parts = [f"{_CS_TYPE_LABELS.get(k, k)} {v}"
             for k, v in sorted(by_type.items(), key=lambda x: -x[1]) if v]
    if parts:
        lines += ["", "유형별: " + ", ".join(parts)]
    by_market = st.get("by_market") or {}
    mparts = [f"{k} {v}"
              for k, v in sorted(by_market.items(), key=lambda x: -x[1]) if v]
    if mparts:
        lines.append("마켓별: " + ", ".join(mparts[:6]))

    if with_comment:
        _append_comment(lines, "CS")
    return "\n".join(lines)


def build_returns_text(with_comment: bool = True) -> str:
    """반품 상태별/유형별/사유별 + 승인대기."""
    st = samba.return_stats()
    if st is None:
        return "❌ 삼바 서버 연결 실패 (반품)."

    total = int(st.get("total") or 0)
    by_status = st.get("by_status") or {}
    by_type = st.get("by_type") or {}
    by_reason = st.get("by_reason") or {}
    waiting = int(by_status.get("requested") or 0)
    lines = [
        "🔄 반품/교환 현황", "",
        f"전체 {total}건 · ⏳승인대기 {waiting}건 · 누적환불 {_fmt_price(st.get('total_refund_amount'))}",
    ]
    sparts = [f"{_RETURN_STATUS_LABELS.get(k, k)} {v}" for k, v in by_status.items() if v]
    if sparts:
        lines += ["", "상태별: " + ", ".join(sparts)]
    tparts = [f"{_CLAIM_TYPE_LABELS.get(k, k)} {v}" for k, v in by_type.items() if v]
    if tparts:
        lines.append("유형별: " + ", ".join(tparts))
    top_reasons = sorted(by_reason.items(), key=lambda x: -x[1])[:3]
    rparts = [f"{k} {v}" for k, v in top_reasons if v]
    if rparts:
        lines.append("사유 Top3: " + ", ".join(rparts))

    if with_comment:
        _append_comment(lines, "반품")
    return "\n".join(lines)


def _require_samba(chat_id: int) -> bool:
    if not samba.is_ready:
        tg_send(chat_id, "⚠️ SAMBA_EMAIL / SAMBA_PASSWORD 환경변수가 없어.\n삼바 연결 설정이 필요해.")
        return False
    return True


def cmd_sales(chat_id: int) -> None:
    if not _require_samba(chat_id):
        return
    tg_send(chat_id, "💰 매출 집계 중...")
    tg_send(chat_id, build_sales_text())


def cmd_order_status(chat_id: int) -> None:
    if not _require_samba(chat_id):
        return
    tg_send(chat_id, "📦 주문 현황 집계 중...")
    tg_send(chat_id, build_order_status_text())


def cmd_cs(chat_id: int) -> None:
    if not _require_samba(chat_id):
        return
    tg_send(chat_id, "💬 CS 현황 집계 중...")
    tg_send(chat_id, build_cs_text())


def cmd_returns(chat_id: int) -> None:
    if not _require_samba(chat_id):
        return
    tg_send(chat_id, "🔄 반품 현황 집계 중...")
    tg_send(chat_id, build_returns_text())


def cmd_help(chat_id: int) -> None:
    samba_status = "✅ 연결됨" if samba.is_ready else "❌ 미연결 (SAMBA_EMAIL/PASSWORD 없음)"
    tg_send(chat_id, (
        "🦙 Hermes 비서 명령어\n"
        "\n"
        "📦 주문 조회\n"
        "  /오늘   — 오늘 주문 현황 요약\n"
        "  /미발주 — 발주 필요한 주문 목록\n"
        "  /처리   — 최신 미발주 주문 분석·발주 준비 (결제 전)\n"
        "\n"
        "📊 보고\n"
        "  /매출     — 오늘+이달 매출·이익·마진·베스트셀러\n"
        "  /주문현황 — 상태별 건수·이행률·전월대비\n"
        "  /CS       — 미답변/답변완료·유형별\n"
        "  /반품     — 반품 상태·유형·사유·승인대기\n"
        "\n"
        "💬 AI 대화\n"
        "  아무 말이나 → Hermes가 답해\n"
        "  /reset  — 대화 기억 초기화\n"
        "\n"
        "⚙️ 시스템\n"
        "  /whoami  — 내 텔레그램 ID\n"
        "  /도움말 — 이 목록\n"
        f"\n삼바 연결: {samba_status}"
    ))


# ══════════════════════════════════════════════════════════════════════════
# 신규 미발주 주문 감지 (백그라운드 스레드)
# ══════════════════════════════════════════════════════════════════════════

_last_unplaced_ids: set[str] = set()
_notify_chat_ids: set[int] = set()


def _poll_new_orders() -> None:
    global _last_unplaced_ids
    if not samba.is_ready:
        return

    time.sleep(30)  # 봇 시작 후 30초 대기 (로그인 완료)
    initial = samba.get_unplaced_orders()
    _last_unplaced_ids = {o.get("id") or o.get("order_number", "") for o in initial}
    print(f"[신규주문감지] 시작. 현재 미발주 {len(_last_unplaced_ids)}건. {NEW_ORDER_POLL_MINUTES}분 주기.")

    while True:
        time.sleep(NEW_ORDER_POLL_MINUTES * 60)
        try:
            current = samba.get_unplaced_orders()
            current_ids = {o.get("id") or o.get("order_number", "") for o in current}
            new_ids = current_ids - _last_unplaced_ids

            if new_ids and _notify_chat_ids:
                new_orders = [o for o in current
                              if (o.get("id") or o.get("order_number", "")) in new_ids]
                lines = [f"🔔 신규 미발주 주문 {len(new_orders)}건 들어왔어!"]
                for o in new_orders[:5]:
                    channel = o.get("channel_name") or "?"
                    product = (o.get("product_name") or "상품명없음")[:25]
                    price = _fmt_price(o.get("sale_price"))
                    lines.append(f"  • [{channel}] {product}  {price}")
                if len(new_orders) > 5:
                    lines.append(f"  ... 외 {len(new_orders) - 5}건")
                lines.append("\n/미발주 — 전체 목록 보기")
                msg = "\n".join(lines)
                for cid in list(_notify_chat_ids):
                    tg_send(cid, msg)

            _last_unplaced_ids = current_ids
        except Exception as e:
            print(f"[신규주문감지] 오류: {e}", file=sys.stderr)


def _daily_report_loop() -> None:
    """매일 DAILY_REPORT_HOUR(KST)에 4종 통합 다이제스트를 발송."""
    if not samba.is_ready or not DAILY_REPORT_HOUR:
        return
    try:
        hour = int(DAILY_REPORT_HOUR)
        if not 0 <= hour <= 23:
            raise ValueError
    except ValueError:
        print(f"[자동보고] DAILY_REPORT_HOUR 값이 잘못됨: {DAILY_REPORT_HOUR!r} — 비활성화", file=sys.stderr)
        return

    print(f"[자동보고] 매일 {hour:02d}:00(KST) 아침 다이제스트 활성.")
    while True:
        now = datetime.now(KST)
        target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        time.sleep(max((target - now).total_seconds(), 1))

        if not _notify_chat_ids:
            continue  # 아직 봇과 대화한 사용자가 없음 → 수신자 없음
        try:
            # 다이제스트는 숫자만(LLM 코멘트 생략)으로 빠르게 — 온디맨드 명령은 코멘트 포함
            digest = "\n\n".join([
                f"🌅 {datetime.now(KST).strftime('%Y년 %m월 %d일')} 아침 보고",
                build_sales_text(with_comment=False),
                build_order_status_text(with_comment=False),
                build_cs_text(with_comment=False),
                build_returns_text(with_comment=False),
            ])
        except Exception as e:
            digest = f"⚠️ 아침 보고 생성 실패: {e}"
        for cid in list(_notify_chat_ids):
            tg_send(cid, digest)


# ══════════════════════════════════════════════════════════════════════════
# 메시지 핸들러
# ══════════════════════════════════════════════════════════════════════════

def handle_message(msg: dict) -> None:
    chat_id: int = msg["chat"]["id"]
    user_id = str(msg.get("from", {}).get("id", ""))
    text = (msg.get("text") or "").strip()
    if not text:
        return

    if text == "/whoami":
        tg_send(chat_id, f"네 텔레그램 user id: {user_id}")
        return

    if ALLOWED and user_id not in ALLOWED:
        tg_send(chat_id, "⛔ 허용되지 않은 사용자입니다.")
        return

    _notify_chat_ids.add(chat_id)  # 신규 주문 알림 대상 등록

    if text == "/start":
        warn = "" if ALLOWED else "\n⚠️ 지금 누구나 사용 가능. /whoami 로 id 확인 후 잠가줘."
        tg_send(chat_id, "🦙 맥미니 Hermes 비서야!\n/도움말 로 전체 명령어 확인." + warn)
        return

    if text == "/reset":
        _HISTORY.pop(chat_id, None)
        tg_send(chat_id, "🧹 대화 기억을 초기화했어.")
        return

    if text in ("/도움말", "/help"):
        cmd_help(chat_id)
        return

    if text in ("/오늘", "/today"):
        cmd_today(chat_id)
        return

    if text in ("/미발주", "/unplaced"):
        cmd_unplaced(chat_id)
        return

    if text in ("/매출", "/sales"):
        cmd_sales(chat_id)
        return

    if text in ("/주문현황", "/orderstatus"):
        cmd_order_status(chat_id)
        return

    if text in ("/CS", "/cs", "/씨에스"):
        cmd_cs(chat_id)
        return

    if text in ("/반품", "/returns"):
        cmd_returns(chat_id)
        return

    # /처리 또는 자연어("주문처리해줘", "처리해줘", "신규주문 처리")
    if (text.startswith(("/처리", "/process"))
            or "주문처리" in text
            or "처리해" in text
            or ("신규" in text and "처리" in text)):
        cmd_process(chat_id)
        return

    # 일반 AI 대화
    try:
        _http_json(f"{TG_API}/sendChatAction",
                   {"chat_id": chat_id, "action": "typing"}, timeout=10)
    except urllib.error.URLError:
        pass
    tg_send(chat_id, ask_hermes(chat_id, text))


# ══════════════════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════════════════

def main() -> None:
    if not TOKEN:
        print("[중단] TELEGRAM_BOT_TOKEN 환경변수가 없습니다.", file=sys.stderr)
        sys.exit(1)
    if not ALLOWED:
        print("[경고] TELEGRAM_ALLOWED_USER_IDS 미설정 — 누구나 사용 가능.", file=sys.stderr)

    samba_status = "연결 대기중" if samba.is_ready else "미연결 (SAMBA_EMAIL/PASSWORD 없음)"
    print(f"[시작] Hermes 비서 봇 — 모델={HERMES_MODEL}, 삼바={samba_status}")

    if samba.is_ready:
        threading.Thread(target=samba._ensure_token, daemon=True).start()
        threading.Thread(target=_poll_new_orders, daemon=True).start()
        threading.Thread(target=_daily_report_loop, daemon=True).start()

    offset = 0
    while True:
        try:
            updates = _http_json(
                f"{TG_API}/getUpdates?timeout=30&offset={offset}", timeout=40)
        except Exception as e:
            print(f"[경고] {e} — 3초 후 재시도", file=sys.stderr)
            time.sleep(3)
            continue
        for upd in updates.get("result", []):
            offset = upd["update_id"] + 1
            message = upd.get("message") or upd.get("edited_message")
            if message:
                try:
                    handle_message(message)
                except Exception as e:
                    print(f"[오류] 처리 실패: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
