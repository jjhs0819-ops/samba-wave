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
  NEW_ORDER_PUSH            (선택) 주문별 실시간 푸시. 기본 OFF. 1/true/on 이면 켜짐.
  NEW_ORDER_POLL_MINUTES    (선택) 신규 미발주 감지 주기(분), 기본 10 (NEW_ORDER_PUSH 켤 때만)
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

import calendar
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
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
# 주문별 실시간 푸시 알림. 기본 OFF — 미발주는 아침 다이제스트에만 표시.
NEW_ORDER_PUSH = os.environ.get("NEW_ORDER_PUSH", "").strip() in ("1", "true", "on", "yes")
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

    # ── 보고용 범용 GET ──────────────────────────────────────────────────────
    def _get(self, path: str, params: dict | None = None, timeout: float = 30.0):
        """삼바 백엔드 GET. 성공 시 dict/list, 실패 시 None.

        401 → 재로그인 후 재시도. 502/503/504·타임아웃 등 일시 오류 →
        백오프 두며 최대 3회 재시도 (게이트웨이 블립·콜드캐시 대응).
        """
        if not self.is_ready:
            return None
        url = f"{SAMBA_URL}{path}"
        last_err = None
        for attempt in range(3):
            try:
                return _http_get(url, params=params,
                                 headers=self._auth_headers(), timeout=timeout)
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code == 401:
                    self._token = None  # 재로그인 후 재시도
                    continue
                if e.code in (502, 503, 504) and attempt < 2:
                    time.sleep(2 * (attempt + 1))  # 일시 게이트웨이 오류 백오프
                    continue
                print(f"[삼바] GET {path} 실패: {e}", file=sys.stderr)
                return None
            except Exception as e:  # 타임아웃/URLError 등 → 재시도
                last_err = e
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                print(f"[삼바] GET {path} 실패: {e}", file=sys.stderr)
                return None
        if last_err:
            print(f"[삼바] GET {path} 재시도 소진: {last_err}", file=sys.stderr)
        return None

    # 보고 영역별 호출 (경로/파라미터는 백엔드 라우터 본문 기준)
    def orders_by_date_range(self, start: str, end: str) -> list | None:
        """결제일(paid_at, KST) 기준 주문 전체 목록. 각 주문에 sale_price·fee_rate·
        cost·collected_product_id·source_url·sourcing_order_number·status 포함."""
        data = self._get("/api/v1/samba/orders/by-date-range",
                         {"start": start, "end": end}, timeout=50)
        return data if isinstance(data, list) else None

    def cs_list(self, start: str, end: str, limit: int = 500) -> list | None:
        """CS 문의 목록 — inquiry_date 기준 필터. 각 item에 inquiry_date·reply_status.
        응답은 {items, total} 구조이므로 items 만 반환."""
        data = self._get("/api/v1/samba/cs-inquiries",
                         {"start_date": start, "end_date": end, "limit": str(limit)})
        if isinstance(data, dict):
            return data.get("items", [])
        return data if isinstance(data, list) else None

    def returns_list(self, start: str, end: str, limit: int = 1000) -> list | None:
        """반품/교환 목록 — order_date 기준 필터. completion_detail·status·memo 포함."""
        return self._get("/api/v1/samba/returns",
                         {"start_date": start, "end_date": end, "limit": str(limit)})


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


def _order_cancelled(o: dict) -> bool:
    """취소/반품 계열 주문인가 (매출 집계 제외 대상)."""
    s = (o.get("status") or "").lower()
    return "cancel" in s or "return" in s


def _order_registered(o: dict) -> bool:
    """등록상품 주문인가 — collected_product_id 있거나, 비SSG이며 source_url 있음.
    (백엔드 주문탭 '등록/미등록' 판정과 동일: order.py registration_filter)."""
    if o.get("collected_product_id"):
        return True
    site = (o.get("source_site") or "").upper()
    return site != "SSG" and bool((o.get("source_url") or "").strip())


def _order_has_so(o: dict) -> bool:
    """발주 주문번호(sourcing_order_number) 입력됨 = 이행 건."""
    return bool((o.get("sourcing_order_number") or "").strip())


def _order_kst_date(o: dict) -> str | None:
    """주문의 결제일(paid_at, 없으면 created_at)을 KST 날짜 문자열로."""
    p = o.get("paid_at") or o.get("created_at")
    if not p:
        return None
    try:
        dt = datetime.fromisoformat(str(p).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST).strftime("%Y-%m-%d")


def _f(o: dict, key: str) -> float:
    try:
        return float(o.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def _sales_metrics(orders: list) -> dict:
    """주문 목록 → 매출/실수익 집계.

    매출 = 등록상품·취소제외. 실수익 = 주문번호+주문금액(cost>0) 입력·취소제외 건의
    백엔드 저장값(profit/revenue) 그대로 합산 (주문탭과 동일).
    """
    sale_orders = [o for o in orders if _order_registered(o) and not _order_cancelled(o)]
    m = [o for o in orders
         if _order_has_so(o) and _f(o, "cost") > 0 and not _order_cancelled(o)]
    pay = sum(_f(o, "total_payment_amount") or _f(o, "sale_price") for o in m)
    profit = sum(_f(o, "profit") for o in m)
    return {
        "sale_orders": sale_orders,
        "sales": sum(_f(o, "sale_price") for o in sale_orders),
        "sales_cnt": len(sale_orders),
        "margin_cnt": len(m),
        "pay": pay,
        "settle": sum(_f(o, "revenue") for o in m),
        "buy": sum(_f(o, "cost") for o in m),
        "profit": profit,
        "rate": (profit / pay * 100) if pay else 0.0,
    }


def _arrow(d: float) -> str:
    return "▲" if d > 0 else ("▼" if d < 0 else "—")


def _last_month_same_period() -> tuple[str, str, str]:
    """전월 동일 기간 (1일 ~ 오늘과 같은 일자). (시작, 끝, '5/20' 라벨) 반환."""
    now = datetime.now(KST)
    y, mth = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
    day = min(now.day, calendar.monthrange(y, mth)[1])
    return f"{y:04d}-{mth:02d}-01", f"{y:04d}-{mth:02d}-{day:02d}", f"{mth}/{day}"


def build_sales_text(with_comment: bool = True) -> str:
    """매출(등록상품) + 실수익/수익률(주문번호·주문금액 입력) + 전월 동기간 비교."""
    now = datetime.now(KST)
    today = _kst_date()
    orders = samba.orders_by_date_range(now.strftime("%Y-%m-01"), today)
    if orders is None:
        return "❌ 삼바 서버 연결 실패 (매출)."

    cur = _sales_metrics(orders)
    today_orders = [o for o in cur["sale_orders"] if _order_kst_date(o) == today]
    today_sales = sum(_f(o, "sale_price") for o in today_orders)

    lines = [
        f"💰 매출 보고 ({now.strftime('%m월 %d일')})",
        "",
        f"▪️ 오늘 매출 {_fmt_price(today_sales)} · {len(today_orders)}건",
        f"▪️ 이달 매출 {_fmt_price(cur['sales'])} · {cur['sales_cnt']}건",
        "",
        f"▪️ 이달 실수익 (주문건수 {cur['margin_cnt']}건)",
        f"· 결제 {_fmt_price(cur['pay'])}",
        f"· 정산 {_fmt_price(cur['settle'])}",
        f"· 구매 {_fmt_price(cur['buy'])}",
        "",
        f"· 수익률 {cur['rate']:.1f}%",
        "",
        f"💵 수익 {_fmt_price(cur['profit'])}",
    ]

    # 전월 동기간 비교 (수익 / 건수 / 수익률)
    lm_start, lm_end, lm_label = _last_month_same_period()
    prev_orders = samba.orders_by_date_range(lm_start, lm_end)
    if prev_orders is not None:
        p = _sales_metrics(prev_orders)
        prof_d = ((cur["profit"] - p["profit"]) / p["profit"] * 100) if p["profit"] else 0.0
        cnt_d = cur["sales_cnt"] - p["sales_cnt"]
        rate_d = cur["rate"] - p["rate"]
        lines += [
            "",
            f"📊 전월 동기간(~{lm_label}) 대비",
            f"· 수익 전월 {_fmt_price(p['profit'])} {_arrow(prof_d)}{abs(prof_d):.0f}%",
            f"· 건수 전월 {p['sales_cnt']}건 {_arrow(cnt_d)}{abs(cnt_d)}건",
            f"· 수익률 전월 {p['rate']:.1f}% {_arrow(rate_d)}{abs(rate_d):.1f}%p",
        ]
    return "\n".join(lines)


def build_order_status_text(with_comment: bool = True) -> str:
    """금일 신규주문 + 전날 총 주문 + 전날 이행(주문번호 입력) 건수."""
    today = _kst_date()
    yday = _kst_date(-1)
    orders = samba.orders_by_date_range(yday, today)  # 결제일 KST: 어제~오늘
    if orders is None:
        return "❌ 삼바 서버 연결 실패 (주문현황)."

    today_cnt = sum(1 for o in orders if _order_kst_date(o) == today)
    yday_orders = [o for o in orders if _order_kst_date(o) == yday]
    yday_cnt = len(yday_orders)
    yday_fulfilled = sum(1 for o in yday_orders if _order_has_so(o))
    rate = (yday_fulfilled / yday_cnt * 100) if yday_cnt else 0

    lines = [
        "📦 주문 처리 현황",
        "",
        f"오늘 신규주문: {today_cnt}건",
        f"전날 총 주문: {yday_cnt}건",
        f"  └ 이행(주문번호 입력): {yday_fulfilled}건 ({rate:.0f}%)",
    ]
    if with_comment:
        _append_comment(lines, "주문 처리")
    return "\n".join(lines)


def _parse_dt(s) -> "datetime | None":
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def build_cs_text(with_comment: bool = True) -> str:
    """전날 CS 처리/미처리 + 미처리 중 24시간 경과 건수."""
    yday = _kst_date(-1)
    items = samba.cs_list(yday, yday)  # inquiry_date 기준 어제
    if items is None:
        return "❌ 삼바 서버 연결 실패 (CS)."

    replied = sum(1 for i in items if i.get("reply_status") == "replied")
    pending_items = [i for i in items if i.get("reply_status") != "replied"]
    pending = len(pending_items)
    # 미처리 중 접수 후 24시간 경과
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    overdue = sum(
        1 for i in pending_items
        if (_parse_dt(i.get("inquiry_date")) or datetime.now(timezone.utc)) < cutoff
    )

    lines = [
        "💬 CS 현황 (전날 기준)",
        "",
        f"✅ 처리: {replied}건 · ⏳ 미처리: {pending}건",
        f"⏰ 미처리 중 24시간 경과: {overdue}건",
    ]
    if with_comment:
        _append_comment(lines, "CS")
    return "\n".join(lines)


# 수거 상태 코드 → 한글 (반품 status 필드 값)
_COLLECT_LABELS = {"not_collected": "미수거", "collecting": "수거중", "collected": "수거완료"}


def build_returns_text(with_comment: bool = True) -> str:
    """반품 — 최근 한 달. 대기중/취소완료 + '반품신청완료' 메모 건의 수거상태."""
    today = _kst_date()
    month_ago = _kst_date(-30)
    rows = samba.returns_list(month_ago, today)  # order_date 기준 최근 30일
    if rows is None:
        return "❌ 삼바 서버 연결 실패 (반품)."

    # 완료내역 토글 기준 = completion_detail (웹 /returns 페이지와 동일)
    waiting = sum(1 for r in rows if (r.get("completion_detail") or "진행중") == "진행중")
    cancel_done = sum(1 for r in rows if r.get("completion_detail") == "취소")

    # 메모에 '반품신청완료' 적힌 건 중 미수거/수거중/수거완료
    collect: dict[str, int] = {"not_collected": 0, "collecting": 0, "collected": 0}
    for r in rows:
        if "반품신청완료" in (r.get("memo") or ""):
            stt = (r.get("status") or "")
            if stt in collect:
                collect[stt] += 1

    lines = [
        "🔄 반품/교환 현황 (최근 한 달)",
        "",
        f"⏳ 대기중: {waiting}건",
        f"✅ 취소완료: {cancel_done}건",
        "",
        "📦 '반품신청완료' 메모 건:",
        f"  미수거 {collect['not_collected']} · 수거중 {collect['collecting']} · 수거완료 {collect['collected']}건",
    ]
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
        # 주문별 실시간 푸시는 기본 OFF — 미발주는 아침 다이제스트에만 표시.
        # 켜고 싶으면 NEW_ORDER_PUSH=1 환경변수 설정.
        if NEW_ORDER_PUSH:
            threading.Thread(target=_poll_new_orders, daemon=True).start()
            print(f"[신규주문감지] 실시간 푸시 ON ({NEW_ORDER_POLL_MINUTES}분 주기)")
        else:
            print("[신규주문감지] 실시간 푸시 OFF (미발주는 아침 다이제스트에만 표시)")
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
