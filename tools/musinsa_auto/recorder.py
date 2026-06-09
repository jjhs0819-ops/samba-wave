#!/usr/bin/env python3
"""무신사 자동화 — 클릭 기록기.

로그인된 전용 프로필로 브라우저를 열고, 사용자가 평소처럼 구매 흐름을
클릭하는 동안 모든 클릭의 '정확한 셀렉터 정보'와 'URL 이동'을 기록한다.
기록 파일을 개발자에게 주면 그대로 재현하는 자동화를 작성한다.

사용:
  python3 recorder.py "https://www.musinsa.com/products/6149001"
  # 진행: 옵션(사이즈) 선택 → 구매하기 → 주문서 화면까지.
  #  ⚠️ 실제 결제(비밀번호 입력)는 하지 말 것! 주문서/결제수단 화면까지만.
  # 결과: ~/hermes-bot/recon/clicks.log  (이 파일을 업로드)
"""

import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

PROFILE_DIR = os.path.expanduser("~/hermes-bot/musinsa_profile")
OUT_DIR = os.path.expanduser("~/hermes-bot/recon")
LOG_PATH = os.path.join(OUT_DIR, "clicks.log")

INIT_JS = r"""
() => {
  if (window.__recHooked) return;
  window.__recHooked = true;
  document.addEventListener('click', (e) => {
    try {
      const el = e.target.closest('button,a,li,div,span,input,label,[role]') || e.target;
      const info = {
        t: new Date().toISOString(),
        kind: 'click',
        url: location.href,
        tag: el.tagName,
        id: el.id || '',
        cls: (el.className && el.className.toString().slice(0, 90)) || '',
        text: (el.innerText || el.value || '').trim().slice(0, 50),
        bId: el.getAttribute && (el.getAttribute('data-button-id') || ''),
        bName: el.getAttribute && (el.getAttribute('data-button-name') || ''),
        testid: el.getAttribute && (el.getAttribute('data-testid') || ''),
        name: el.getAttribute && (el.getAttribute('name') || ''),
        href: el.getAttribute && (el.getAttribute('href') || ''),
      };
      if (typeof window.__recordClick === 'function') window.__recordClick(JSON.stringify(info));
    } catch (err) {}
  }, true);
}
"""


def main() -> None:
    if len(sys.argv) < 2:
        print("사용법: python3 recorder.py \"무신사_상품_URL\"")
        sys.exit(1)
    url = sys.argv[1]
    os.makedirs(OUT_DIR, exist_ok=True)
    logf = open(LOG_PATH, "w", encoding="utf-8")

    def record(source, payload):
        try:
            logf.write(payload + "\n")
            logf.flush()
            d = json.loads(payload)
            print(f"  📍 클릭: <{d['tag']}> '{d['text']}' "
                  f"[id={d.get('bId') or d.get('id')}] @ {d['url'][:50]}")
        except Exception:
            pass

    def attach(page):
        page.on("framenavigated", lambda fr: (
            logf.write(json.dumps({"kind": "nav", "url": fr.url}) + "\n"),
            logf.flush(),
            print(f"  ➡️  이동: {fr.url[:80]}") if fr == page.main_frame else None,
        ))

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx.expose_binding("__recordClick", record)
        ctx.add_init_script(INIT_JS)
        ctx.on("page", attach)

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        attach(page)
        page.goto(url, wait_until="domcontentloaded")
        page.evaluate(INIT_JS)  # 첫 페이지에도 즉시 주입

        print("\n" + "=" * 64)
        print("🟢 기록 시작! 지금부터 평소처럼 구매를 진행하세요:")
        print("   1) 사이즈/옵션 선택  2) 구매하기  3) 주문서 화면까지")
        print("   ⚠️  실제 결제 비밀번호는 입력하지 마세요! (주문서까지만)")
        print("   끝나면 이 터미널로 돌아와 Enter 를 누르세요.")
        print(f"   (기록 파일: {LOG_PATH})")
        print("=" * 64 + "\n")
        input("구매 흐름 클릭이 끝나면 Enter ▶ ")

        logf.close()
        print(f"\n✅ 기록 완료: {LOG_PATH}")
        print("📤 이 파일을 개발자에게 업로드하세요.")
        ctx.close()


if __name__ == "__main__":
    main()
