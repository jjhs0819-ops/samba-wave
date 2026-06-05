#!/usr/bin/env python3
"""맥미니 Hermes 두뇌를 텔레그램으로 쓰는 최소 봇 (Phase 1).

- 의존성 0 (파이썬 표준 라이브러리만 사용) → `python3 telegram_brain_bot.py` 로 바로 실행.
- 폴링 방식(getUpdates long-poll) → 맥미니를 인터넷에 노출하지 않아 안전.
- 두뇌 호출은 OLLAMA_BASE_URL(기본 127.0.0.1:11434)의 Ollama /api/chat.

환경변수:
  TELEGRAM_BOT_TOKEN        (필수) @BotFather 가 준 토큰
  TELEGRAM_ALLOWED_USER_IDS (권장) 콤마 구분 숫자 — 이 사람들만 봇 사용. 비우면 누구나 사용(경고).
  OLLAMA_BASE_URL           (선택) 기본 http://127.0.0.1:11434
  HERMES_MODEL              (선택) 기본 hermes3:8b

명령:
  /start  안내
  /reset  대화 기억 초기화
  /whoami 내 텔레그램 user id 확인(allowlist 설정용)
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED = {
    s.strip()
    for s in os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").split(",")
    if s.strip()
}
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
HERMES_MODEL = os.environ.get("HERMES_MODEL", "hermes3:8b")

TG_API = f"https://api.telegram.org/bot{TOKEN}"

# chat_id -> 최근 대화 메시지 리스트(간단한 in-memory 기억). 재시작하면 초기화됨.
_HISTORY: dict[int, list[dict[str, str]]] = {}
_MAX_TURNS = 12  # 최근 N개 메시지만 유지(컨텍스트·속도 관리)

SYSTEM_PROMPT = (
    "너는 한국어로 답하는 친절하고 유능한 개인 비서야. "
    "요약·번역·아이디어·정리를 잘 돕고, 모르면 모른다고 솔직히 말해."
)


def _http_json(url: str, payload: dict | None = None, timeout: float = 60.0) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def tg_send(chat_id: int, text: str) -> None:
    # 텔레그램 메시지 길이 제한(4096) 보호
    for chunk_start in range(0, len(text), 4000):
        chunk = text[chunk_start : chunk_start + 4000] or "(빈 응답)"
        try:
            _http_json(
                f"{TG_API}/sendMessage",
                {"chat_id": chat_id, "text": chunk},
                timeout=30,
            )
        except urllib.error.URLError as e:
            print(f"[경고] 메시지 전송 실패: {e}", file=sys.stderr)


def ask_hermes(chat_id: int, user_text: str) -> str:
    history = _HISTORY.setdefault(chat_id, [])
    history.append({"role": "user", "content": user_text})
    # 최근 _MAX_TURNS 개만 유지
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
        return f"⚠️ 두뇌(Ollama) 호출 실패: {e}\nOllama 앱이 켜져 있는지 확인해줘."
    except Exception as e:  # noqa: BLE001 - 봇은 죽지 않고 사용자에게 알림
        return f"⚠️ 오류: {e}"

    if not answer:
        return "(두뇌가 빈 응답을 줬어. 다시 시도해줘.)"
    history.append({"role": "assistant", "content": answer})
    return answer


def handle_message(msg: dict) -> None:
    chat_id = msg["chat"]["id"]
    user_id = str(msg.get("from", {}).get("id", ""))
    text = (msg.get("text") or "").strip()
    if not text:
        return

    if text == "/whoami":
        tg_send(chat_id, f"네 텔레그램 user id: {user_id}\n(allowlist 에 넣어 봇을 잠가둬.)")
        return

    # allowlist 보안 — 설정돼 있으면 본인만 사용
    if ALLOWED and user_id not in ALLOWED:
        tg_send(chat_id, "⛔ 허용되지 않은 사용자입니다.")
        print(f"[차단] user_id={user_id} 비허용 접근", file=sys.stderr)
        return

    if text == "/start":
        warn = "" if ALLOWED else "\n⚠️ 지금 누구나 사용 가능 상태. /whoami 로 id 확인 후 잠가줘."
        tg_send(
            chat_id,
            "🦙 맥미니 Hermes 비서야. 무엇이든 물어봐!\n"
            "/reset 으로 대화 기억을 지울 수 있어." + warn,
        )
        return

    if text == "/reset":
        _HISTORY.pop(chat_id, None)
        tg_send(chat_id, "🧹 대화 기억을 초기화했어.")
        return

    # 타이핑 표시 후 두뇌에게 질문
    try:
        _http_json(
            f"{TG_API}/sendChatAction",
            {"chat_id": chat_id, "action": "typing"},
            timeout=10,
        )
    except urllib.error.URLError:
        pass
    tg_send(chat_id, ask_hermes(chat_id, text))


def main() -> None:
    if not TOKEN:
        print("[중단] TELEGRAM_BOT_TOKEN 환경변수가 없습니다.", file=sys.stderr)
        sys.exit(1)
    if not ALLOWED:
        print(
            "[경고] TELEGRAM_ALLOWED_USER_IDS 미설정 — 누구나 봇을 사용할 수 있습니다. "
            "텔레그램에서 /whoami 로 본인 id 확인 후 설정 권장.",
            file=sys.stderr,
        )
    print(f"[시작] Hermes 텔레그램 봇 — 모델={HERMES_MODEL}, 두뇌={OLLAMA_BASE_URL}")

    offset = 0
    while True:
        try:
            updates = _http_json(
                f"{TG_API}/getUpdates?timeout=30&offset={offset}",
                timeout=40,
            )
        except urllib.error.URLError as e:
            print(f"[경고] getUpdates 실패: {e} — 3초 후 재시도", file=sys.stderr)
            time.sleep(3)
            continue
        except Exception as e:  # noqa: BLE001
            print(f"[경고] {e} — 3초 후 재시도", file=sys.stderr)
            time.sleep(3)
            continue

        for upd in updates.get("result", []):
            offset = upd["update_id"] + 1
            message = upd.get("message") or upd.get("edited_message")
            if message:
                try:
                    handle_message(message)
                except Exception as e:  # noqa: BLE001 - 한 메시지 실패가 봇을 죽이지 않게
                    print(f"[오류] 메시지 처리 실패: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
