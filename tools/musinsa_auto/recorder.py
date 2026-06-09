#!/usr/bin/env python3
"""무신사 자동화 — 클릭 기록기 (v3, 폴링 방식).

console.log/expose_binding 이 사이트 환경에서 막히는 문제를 우회한다.
페이지의 window.__recClicks 배열에 클릭을 쌓아두고, 파이썬이 0.3초마다
직접 읽어가서(evaluate) 파일에 기록한다. 사이트가 무엇을 하든 안 막힌다.

사용:
  python3 recorder.py "https://www.musinsa.com/products/6149001"
  # 옵션선택 → 구매하기 → 주문서 화면까지. (실제 결제 비번 입력 금지)
  # 결과: ~/hermes-bot/recon/clicks.log
"""

import json
import os
import select
import sys

from playwright.sync_api import sync_playwright

PROFILE_DIR = os.path.expanduser("~/hermes-bot/musinsa_profile")
OUT_DIR = os.path.expanduser("~/hermes-bot/recon")
LOG_PATH = os.path.join(OUT_DIR, "clicks.log")

# 클릭을 window.__recClicks 배열에 쌓는다 (navigation 시 새 문서에 다시 주입됨)
INIT_JS = r"""
(() => {
  window.__recClicks = window.__recClicks || [];
  if (window.__recHooked) return;
  window.__recHooked = true;
  window.addEventListener('click', (e) => {
    try {
      const el = (e.target && e.target.closest)
        ? (e.target.closest('button,a,li,label,[role],input,div,span') || e.target)
        : e.target;
      if (!el) return;
      window.__recClicks.push({
        kind: 'click',
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
      });
    } catch (err) {}
  }, true);
})();
"""

DRAIN_JS = "() => { const c = window.__recClicks || []; window.__recClicks = []; return c; }"


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

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx.add_init_script(INIT_JS)

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")

        print("\n" + "=" * 64)
        print("🟢 기록 시작! 클릭하면 아래에 '📍 클릭' 이 떠야 정상입니다.")
        print("   1) 사이즈/옵션 선택  2) 구매하기  3) 주문서  4) 결제 비번 화면")
        print("   ⚠️  실제 결제 비밀번호는 입력하지 마세요!")
        print("   💾 화면 저장: 원하는 화면에서 터미널에 'd' 입력 후 Enter")
        print("      → 꼭 저장할 화면: (a)사이즈 목록이 열린 상태 (b)주문서 (c)비번 화면")
        print("   🏁 끝내기: 그냥 Enter (빈 줄)")
        print("=" * 64 + "\n", flush=True)

        last_urls: dict = {}
        count = 0
        dump_idx = 0

        def do_dump() -> None:
            nonlocal dump_idx
            dump_idx += 1
            for i, pg in enumerate(list(ctx.pages)):
                try:
                    base = os.path.join(OUT_DIR, f"dump{dump_idx}_p{i}")
                    pg.screenshot(path=base + ".png", full_page=True)
                    with open(base + ".html", "w", encoding="utf-8") as f:
                        f.write(pg.content())
                    print(f"  💾 저장: {base}.png / .html  ({pg.url[:48]})", flush=True)
                except Exception as e:
                    print(f"  💾 저장 실패(탭{i}): {e}", flush=True)

        while True:
            # 모든 열린 탭을 순회하며 클릭 버퍼를 비워 기록
            for pg in list(ctx.pages):
                try:
                    pg.evaluate(INIT_JS)  # 혹시 미주입된 문서면 후킹 보장(중복 무해)
                    # URL 이동 감지
                    cur = pg.url
                    if last_urls.get(id(pg)) != cur:
                        last_urls[id(pg)] = cur
                        write_line({"kind": "nav", "url": cur})
                        print(f"  ➡️  이동: {cur[:78]}", flush=True)
                    clicks = pg.evaluate(DRAIN_JS)
                    for d in clicks:
                        write_line(d)
                        count += 1
                        label = d.get("bId") or d.get("id") or d.get("testid") or ""
                        print(f"  📍 클릭 <{d['tag']}> '{d['text']}' [{label}] "
                              f"@ {d['url'][:46]}", flush=True)
                except Exception:
                    pass  # 페이지 이동/닫힘 중이면 다음 루프에

            # 입력 감지 (0.3초 타임아웃 폴링): 'd'=화면저장, 빈줄=종료
            r, _, _ = select.select([sys.stdin], [], [], 0.3)
            if r:
                cmd = sys.stdin.readline().strip().lower()
                if cmd == "d":
                    do_dump()
                else:
                    break

        # 종료 직전 마지막 버퍼 한 번 더 수거
        for pg in list(ctx.pages):
            try:
                for d in pg.evaluate(DRAIN_JS):
                    write_line(d)
                    count += 1
            except Exception:
                pass

        logf.close()
        print(f"\n✅ 기록 완료: 클릭 {count}건 → {LOG_PATH}")
        print("📤 이 파일을 개발자에게 업로드하세요.", flush=True)
        ctx.close()


if __name__ == "__main__":
    main()
