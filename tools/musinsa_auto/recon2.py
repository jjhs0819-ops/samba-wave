#!/usr/bin/env python3
"""무신사 자동화 2-2단계 — '구매하기' 클릭 후 옵션 시트 정찰.

상품 페이지는 정적 HTML에 사이즈 옵션이 없다. '구매하기'를 눌러야
옵션 선택 시트(bottom sheet)가 뜨므로, 그 상태를 캡처한다.

사용:
  python3 recon2.py "https://www.musinsa.com/products/6149001"
  # 결과: ~/hermes-bot/recon/after_buy.png / after_buy.html / sheet.txt
"""

import os
import sys

from playwright.sync_api import sync_playwright

PROFILE_DIR = os.path.expanduser("~/hermes-bot/musinsa_profile")
OUT_DIR = os.path.expanduser("~/hermes-bot/recon")


def main() -> None:
    if len(sys.argv) < 2:
        print("사용법: python3 recon2.py \"무신사_상품_URL\"")
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
        print(f"[정찰2] 페이지 여는 중: {url}")
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)

        # '구매하기' 버튼 클릭
        print("[정찰2] '구매하기' 클릭 시도...")
        clicked = False
        for sel in ["button:has-text('구매하기')", "text=구매하기"]:
            try:
                page.locator(sel).first.click(timeout=4000)
                clicked = True
                print(f"  ✅ 클릭 성공: {sel}")
                break
            except Exception as e:
                print(f"  - 실패({sel}): {e}")
        if not clicked:
            print("  ⚠️ 구매하기 버튼을 못 찾음. 화면만 캡처합니다.")

        page.wait_for_timeout(3500)  # 옵션 시트 렌더 대기

        # 스크린샷
        png = os.path.join(OUT_DIR, "after_buy.png")
        page.screenshot(path=png, full_page=True)
        print(f"  ✅ 스크린샷: {png}")

        # HTML (이제 옵션 시트 포함)
        html_path = os.path.join(OUT_DIR, "after_buy.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(page.content())
        print(f"  ✅ HTML: {html_path}")

        # 옵션 시트 안의 클릭 가능 요소 덤프
        dump = ["===== 클릭 가능한 옵션 후보 (li / button / [role=option] / data-* ) ====="]
        try:
            els = page.query_selector_all(
                "li, button, [role='option'], [role='button'], "
                "div[class*='Option'], div[class*='option'], div[class*='Sheet'], a[data-option-no]"
            )
            seen = set()
            for el in els:
                try:
                    txt = (el.inner_text() or "").strip().replace("\n", " ")
                except Exception:
                    continue
                if not txt or len(txt) > 60:
                    continue
                tag = el.evaluate("e=>e.tagName")
                cls = el.get_attribute("class") or ""
                # 데이터 속성 수집
                data_attrs = el.evaluate(
                    "e=>Object.fromEntries([...e.attributes].filter(a=>a.name.startsWith('data-')).map(a=>[a.name,a.value]))"
                )
                key = f"{tag}|{txt}|{cls[:30]}"
                if key in seen:
                    continue
                seen.add(key)
                dump.append(f"<{tag}> text='{txt}' class='{cls[:60]}' data={data_attrs}")
        except Exception as e:
            dump.append(f"(덤프 오류: {e})")

        sheet_path = os.path.join(OUT_DIR, "sheet.txt")
        with open(sheet_path, "w", encoding="utf-8") as f:
            f.write("\n".join(dump))
        print(f"  ✅ 옵션시트 덤프: {sheet_path}")

        print("\n📤 ~/hermes-bot/recon 의 after_buy.png / after_buy.html / sheet.txt 를 업로드하세요.")
        input("Enter로 닫기 ▶ ")
        ctx.close()


if __name__ == "__main__":
    main()
