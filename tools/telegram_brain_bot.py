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
  NEW_ORDER_POLL_MINUTES    (선택) 신규 미발주 감지 주기(분), 기본 10

명령:
  /오늘    — 오늘 주문 현황 요약
  /미발주  — 발주 필요한 주문 목록 (최근 7일)
  /도움말  — 전체 명령어 안내
  /reset   — 대화 기억 초기화
  /whoami  — 내 텔레그램 user id
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
NEW_ORDER_POLL_MINUTES = int(os.environ.get("NEW_ORDER_POLL_MINUTES", "10"))

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
            resp = _http_json(
                f"{SAMBA_URL}/api/v1/auth/email/login",
                {"email": SAMBA_EMAIL, "password": SAMBA_PASSWORD},
                timeout=15,
            )
            self._token = resp.get("app_auth_token")
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
        return {"Authorization": f"Bearer {token}"} if token else {}

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


def cmd_help(chat_id: int) -> None:
    samba_status = "✅ 연결됨" if samba.is_ready else "❌ 미연결 (SAMBA_EMAIL/PASSWORD 없음)"
    tg_send(chat_id, (
        "🦙 Hermes 비서 명령어\n"
        "\n"
        "📦 주문 조회\n"
        "  /오늘   — 오늘 주문 현황 요약\n"
        "  /미발주 — 발주 필요한 주문 목록\n"
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
