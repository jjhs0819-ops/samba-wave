#!/usr/bin/env python3
"""무신사 자동화 2단계 — 상품 페이지 정찰 (DOM·스크린샷 수집).

옵션 선택/장바구니/결제 자동화 코드를 정확히 작성하기 위해,
실제 무신사 상품 페이지의 HTML과 스크린샷, 그리고 옵션 후보 요소를 덤프한다.
저장된 파일을 개발자에게 업로드하면 정확한 셀렉터로 자동화를 만든다.

사용:
  python3 recon.py "https://www.musinsa.com/products/4298203"
  # 결과: ~/hermes-bot/recon/ 폴더에 product.html, product.png, options.txt
"""

import os
import sys

from playwright.sync_api import sync_playwright

PROFILE_DIR = os.path.expanduser("~/hermes-bot/musinsa_profile")
OUT_DIR = os.path.expanduser("~/hermes-bot/recon")


def main() -> None:
    if len(sys.argv) < 2:
        print("사용법: python3 recon.py \"무신사_상품_URL\"")
        sys.exit(1)
    url = sys.argv[1]
    os.makedirs(OUT_DIR, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print(f"[정찰] 페이지 여는 중: {url}")
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)  # 동적 로딩 대기

        # 1) 전체 스크린샷
        png = os.path.join(OUT_DIR, "product.png")
        page.screenshot(path=png, full_page=True)
        print(f"  ✅ 스크린샷: {png}")

        # 2) HTML 저장
        html_path = os.path.join(OUT_DIR, "product.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(page.content())
        print(f"  ✅ HTML: {html_path}")

        # 3) 옵션 후보 요소 덤프 (select, 옵션 버튼, 구매/장바구니 버튼 추정)
        dump = []
        try:
            dump.append("===== <select> 요소 =====")
            for i, sel in enumerate(page.query_selector_all("select")):
                opts = [o.inner_text().strip() for o in sel.query_selector_all("option")]
                dump.append(f"[select {i}] name={sel.get_attribute('name')} "
                            f"id={sel.get_attribute('id')} class={sel.get_attribute('class')}")
                dump.append("   옵션들: " + " | ".join(opts[:30]))

            dump.append("\n===== 버튼/클릭요소 (텍스트 기준) =====")
            keywords = ["구매", "장바구니", "옵션", "사이즈", "선택", "결제", "담기"]
            for el in page.query_selector_all("button, a, [role='button'], div[class*='option']"):
                try:
                    txt = (el.inner_text() or "").strip().replace("\n", " ")
                except Exception:
                    continue
                if txt and any(k in txt for k in keywords) and len(txt) < 40:
                    dump.append(f"  <{el.evaluate('e=>e.tagName')}> "
                                f"class={el.get_attribute('class')} text='{txt}'")
        except Exception as e:
            dump.append(f"(덤프 중 오류: {e})")

        opt_path = os.path.join(OUT_DIR, "options.txt")
        with open(opt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(dump))
        print(f"  ✅ 옵션후보: {opt_path}")

        print("\n📤 이제 ~/hermes-bot/recon 폴더의 3개 파일을 개발자에게 업로드하세요.")
        input("Enter로 브라우저 닫기 ▶ ")
        ctx.close()


if __name__ == "__main__":
    main()
