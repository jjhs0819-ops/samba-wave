#!/usr/bin/env python3
"""무신사 자동화 1단계 — 전용 브라우저 프로필에 무신사 로그인 (1회용).

Playwright의 '지속 프로필'에 무신사 로그인 세션을 저장한다.
이후 모든 자동화는 이 프로필을 재사용하므로 매번 로그인할 필요가 없다.

⚠️ 이 스크립트는 브라우저 창이 보여야 하므로, 맥미니 화면을 직접 보거나
   화면공유(Screen Sharing)로 접속한 상태에서 실행해야 한다.

사용:
  pip3 install playwright
  python3 -m playwright install chromium
  python3 setup_profile.py
"""

import os

from playwright.sync_api import sync_playwright

PROFILE_DIR = os.path.expanduser("~/hermes-bot/musinsa_profile")


def main() -> None:
    os.makedirs(PROFILE_DIR, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.musinsa.com/auth/login")

        print("\n" + "=" * 60)
        print("🖥️  열린 브라우저에서 무신사에 로그인하세요.")
        print("   로그인이 끝나 메인/마이페이지가 보이면,")
        print("   이 터미널로 돌아와 Enter 키를 누르세요.")
        print("=" * 60 + "\n")
        input("로그인 완료 후 Enter ▶ ")

        # 로그인 상태 간단 확인
        try:
            page.goto("https://www.musinsa.com/mypage", wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            print("✅ 프로필 저장 완료:", PROFILE_DIR)
            print("   (다음부터는 이 프로필로 자동 로그인 상태가 유지됩니다.)")
        except Exception as e:
            print(f"확인 중 경고: {e}")
        finally:
            ctx.close()


if __name__ == "__main__":
    main()
