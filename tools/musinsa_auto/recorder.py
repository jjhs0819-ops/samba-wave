#!/usr/bin/env python3
"""무신사 자동화 — 클릭 기록기 (v2, console 기반).

로그인된 전용 프로필로 브라우저를 열고, 사용자가 평소처럼 구매 흐름을
클릭하는 동안 모든 클릭의 셀렉터 정보와 URL 이동을 기록한다.
클릭 정보를 console.log('__REC__'+json) 로 흘려보내고 파이썬이 수집한다.
(expose_binding 보다 환경 영향이 적고 안정적)

사용:
  python3 recorder.py "https://www.musinsa.com/products/6149001"
  # 옵션선택 → 구매하기 → 주문서 화면까지. (실제 결제 비번 입력 금지)
  # 결과: ~/hermes-bot/recon/clicks.log
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright

PROFILE_DIR = os.path.expanduser("~/hermes-bot/musinsa_profile")
OUT_DIR = os.path.expanduser("~/hermes-bot/recon")
LOG_PATH = os.path.join(OUT_DIR, "clicks.log")

# window 최상위 capture 단계에서 click/pointerdown 둘 다 후킹 → console로 전송
INIT_JS = r"""
(() => {
  if (window.__recHooked) return;
  window.__recHooked = true;
  const grab = (e) => {
    try {
      const el = (e.target && e.target.closest)
        ? (e.target.closest('button,a,li,label,[role],input,div,span') || e.target)
        : e.target;
      if (!el) return;
      const info = {
        kind: 'click',
        ev: e.type,
        url: location.href,
        tag: el.tagName,
        id: el.id || '',
        cls: (el.className && el.className.toString().slice(0, 90)) || '',
        text: (el.innerText || el.value || '').trim().slice(0, 50),
        bId: (el.getAttribute && el.getAttribute('data-button-id')) || '',
        bName: (el.getAttribute && el.getAttribute('data-button-name')) || '',
        testid: (el.getAttribute && el.getAttribute('data-testid')) || '',
        name: (el.getAttribute && el.getAttribute('name')) || '',
        href: (el.getAttribute && el.getAttribute('href')) || '',
      };
      console.log('__REC__' + JSON.stringify(info));
    } catch (err) {}
  };
  window.addEventListener('click', grab, true);
  console.log('__REC__' + JSON.stringify({kind: 'hooked', url: location.href}));
})();
"""


def main() -> None:
    if len(sys.argv) < 2:
        print("사용법: python3 recorder.py \"무신사_상품_URL\"")
        sys.exit(1)
    url = sys.argv[1]
    os.makedirs(OUT_DIR, exist_ok=True)
    logf = open(LOG_PATH, "w", encoding="utf-8")

    def write_line(obj: dict) -> None:
        logf.write(json.dumps(obj, ensure_ascii=False) + "\n")
        logf.flush()

    def on_console(msg) -> None:
        try:
            txt = msg.text
        except Exception:
            return
        if not txt or not txt.startswith("__REC__"):
            return
        try:
            d = json.loads(txt[len("__REC__"):])
        except Exception:
            return
        write_line(d)
        if d.get("kind") == "click":
            label = d.get("bId") or d.get("id") or d.get("testid") or ""
            print(f"  📍 클릭 <{d['tag']}> '{d['text']}' [{label}] @ {d['url'][:48]}")
        elif d.get("kind") == "hooked":
            print(f"  🔗 후킹됨 @ {d['url'][:48]}")

    def attach(page) -> None:
        page.on("console", on_console)
        page.on("framenavigated", lambda fr: (
            write_line({"kind": "nav", "url": fr.url})
            if fr == page.main_frame else None,
            print(f"  ➡️  이동: {fr.url[:78]}") if fr == page.main_frame else None,
        ))

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx.add_init_script(INIT_JS)
        ctx.on("page", attach)

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        attach(page)
        page.goto(url, wait_until="domcontentloaded")
        page.evaluate(INIT_JS)  # 첫 페이지 즉시 후킹

        print("\n" + "=" * 64)
        print("🟢 기록 시작! 클릭하면 아래에 '📍 클릭' 이 떠야 정상입니다.")
        print("   1) 사이즈/옵션 선택  2) 구매하기  3) 주문서 화면까지")
        print("   ⚠️  실제 결제 비밀번호는 입력하지 마세요! (주문서까지만)")
        print("   끝나면 이 터미널로 돌아와 Enter ▶")
        print("=" * 64 + "\n")
        input("구매 흐름 클릭이 끝나면 Enter ▶ ")

        logf.close()
        print(f"\n✅ 기록 완료: {LOG_PATH}")
        print("📤 이 파일을 개발자에게 업로드하세요.")
        ctx.close()


if __name__ == "__main__":
    main()
