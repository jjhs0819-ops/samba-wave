#!/usr/bin/env python3
"""무신사 자동 구매 스크립트.

전체 흐름:
  상품 → 옵션(사이즈) 선택 → 구매하기 → 주문서(order-form)
       → 결제하기 → money-payment → 결제하기 → NICE Pay 비번 6자리 → 완료

⚠️ 단계(stage)로 안전하게 끊어서 실행:
  order : 주문서까지만. (결제 안 함, 돈 안 나감)  ← 가장 먼저 이걸로 테스트!
  pay   : money-payment 화면까지. (비번 안 누름, 돈 안 나감)
  full  : 비번까지 전부 자동. (실제 결제됨!)

사용:
  # 1) 안전 테스트 (돈 안 나감)
  python3 purchase.py "https://www.musinsa.com/products/6149001" --size L --stage order

  # 2) 결제 직전까지
  python3 purchase.py "...URL..." --size L --stage pay

  # 3) 완전 자동 결제 (비번은 환경변수로)
  export MUSINSA_PIN=123456
  python3 purchase.py "...URL..." --size L --stage full --max 150000
"""

import argparse
import os
import sys
import time

from playwright.sync_api import sync_playwright

PROFILE_DIR = os.path.expanduser("~/hermes-bot/musinsa_profile")
SHOT_DIR = os.path.expanduser("~/hermes-bot/shots")


def log(msg: str) -> None:
    print(f"  {msg}", flush=True)


def shot(page, name: str) -> None:
    os.makedirs(SHOT_DIR, exist_ok=True)
    path = os.path.join(SHOT_DIR, f"{name}.png")
    try:
        page.screenshot(path=path, full_page=True)
        log(f"📸 {path}")
    except Exception as e:
        log(f"📸 실패: {e}")


def select_size(page, size: str) -> None:
    """옵션 드롭다운을 열고 원하는 사이즈를 선택."""
    log(f"옵션 드롭다운 열기...")
    page.locator('[data-button-id="option_type"]').first.click(timeout=8000)
    page.wait_for_timeout(800)

    # 사이즈 항목: data-button-id="select_optionvalue" 중 첫 줄(사이즈명)이 정확히 일치하는 것
    items = page.locator('[data-button-id="select_optionvalue"]')
    n = items.count()
    log(f"옵션 {n}개 발견. '{size}' 찾는 중...")
    target = None
    for i in range(n):
        it = items.nth(i)
        txt = (it.inner_text() or "").strip()
        first_line = txt.split("\n")[0].strip()
        if first_line.upper() == size.upper():
            target = it
            break
    if target is None:
        # 부분 일치 fallback (품절 등으로 정확 매칭 실패 시)
        for i in range(n):
            it = items.nth(i)
            if (it.inner_text() or "").strip().upper().startswith(size.upper()):
                target = it
                break
    if target is None:
        raise RuntimeError(f"사이즈 '{size}' 옵션을 찾지 못했습니다. (품절이거나 사이즈명 불일치)")
    log(f"사이즈 '{size}' 선택")
    target.click(timeout=8000)
    page.wait_for_timeout(800)


def click_buy(page) -> None:
    log("구매하기 클릭...")
    for sel in ['[data-button-id="2depth_buy_btn"]', 'button:has-text("구매하기")']:
        try:
            page.locator(sel).first.click(timeout=5000)
            return
        except Exception:
            continue
    raise RuntimeError("구매하기 버튼을 찾지 못했습니다.")


def read_total_amount(page) -> int:
    """주문서의 '총 결제 금액'을 정수(원)로 읽어온다. 실패하면 -1."""
    import re
    try:
        body = page.locator("body").inner_text()
        # "총 결제 금액 ... 8% 45,120원" → 3자리 이상 숫자만 인정(8% 같은 한자리 무시)
        for pat in (r"총\s*결제\s*금액[\s\S]{0,30}?([\d,]{3,})\s*원",
                    r"([\d,]{4,})\s*원\s*결제하기"):
            m = re.search(pat, body)
            if m:
                return int(m.group(1).replace(",", ""))
    except Exception:
        pass
    return -1


def enter_pin(pin_page, pin: str) -> None:
    """NICE Pay nFilter 키패드에 비번을 클릭으로 입력."""
    log(f"비밀번호 {len(pin)}자리 입력 중...")
    pin_page.wait_for_selector("button.nfilter_keypad_button", timeout=15000)
    pin_page.wait_for_timeout(500)
    for d in pin:
        # 보이는(display:block) 키패드 안의 해당 숫자 버튼만 클릭
        btn = pin_page.locator(
            f"button.nfilter_keypad_button[aria-label='{d}']"
        ).locator("visible=true").first
        btn.click(timeout=5000)
        pin_page.wait_for_timeout(180)  # 사람처럼 약간의 간격
    log("입력완료 클릭")
    try:
        pin_page.locator("button#nfilter_enter").locator("visible=true").first.click(timeout=4000)
    except Exception:
        log("입력완료 버튼 자동 진행(또는 6자리 후 자동제출)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--size", required=True, help="선택할 사이즈 (예: L)")
    ap.add_argument("--stage", choices=["order", "pay", "full"], default="order")
    ap.add_argument("--max", type=int, default=150000, help="최대 결제 허용 금액(원)")
    ap.add_argument("--pin", default=os.environ.get("MUSINSA_PIN", ""),
                    help="결제 비밀번호 (기본: 환경변수 MUSINSA_PIN)")
    args = ap.parse_args()

    if args.stage == "full" and not args.pin:
        print("❌ full 단계는 비밀번호가 필요합니다. --pin 또는 MUSINSA_PIN 설정.")
        sys.exit(1)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        print(f"\n▶ 상품 열기: {args.url}")
        page.goto(args.url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        # 1~3) 옵션선택 + 구매하기
        select_size(page, args.size)
        click_buy(page)

        # order-form 도착 대기
        log("주문서 이동 대기...")
        try:
            page.wait_for_url("**/order/order-form**", timeout=15000)
        except Exception:
            log(f"(현재 URL: {page.url})")
        page.wait_for_timeout(2500)
        shot(page, "order_form")

        # 금액 확인 (상한 체크)
        total = read_total_amount(page)
        if total >= 0:
            log(f"💰 총 결제 금액: {total:,}원 (상한 {args.max:,}원)")
            if total > args.max:
                print(f"🛑 금액 상한 초과! ({total:,} > {args.max:,}) 결제 중단.")
                input("Enter로 종료 ▶ ")
                ctx.close()
                return
        else:
            log("⚠️ 총 결제 금액을 읽지 못함")

        if args.stage == "order":
            print("\n✅ [order 단계] 주문서까지 도달. 결제는 진행하지 않았습니다.")
            input("확인 후 Enter로 종료 ▶ ")
            ctx.close()
            return

        # 4) 적립금 선할인 (있으면)
        try:
            page.locator("#pre-discount").first.click(timeout=2500)
            log("적립금 선할인 선택")
            page.wait_for_timeout(500)
        except Exception:
            log("적립금 선할인 항목 없음(스킵)")

        # 5) order-form 결제하기 → money-payment (팝업/이동 대기)
        log("주문서 '결제하기' 클릭...")
        page.locator('button:has-text("결제하기")').first.click(timeout=8000)

        # money-payment 페이지 찾기 (같은 탭 이동 또는 새 탭)
        page.wait_for_timeout(3000)
        money_page = None
        for pg in ctx.pages:
            if "musinsapayments.com" in pg.url:
                money_page = pg
                break
        money_page = money_page or page
        try:
            money_page.wait_for_url("**/money-payment**", timeout=15000)
        except Exception:
            log(f"(money URL: {money_page.url})")
        money_page.wait_for_timeout(2000)
        shot(money_page, "money_payment")

        if args.stage == "pay":
            print("\n✅ [pay 단계] 결제수단 화면까지 도달. 비번/결제는 진행하지 않았습니다.")
            input("확인 후 Enter로 종료 ▶ ")
            ctx.close()
            return

        # 6) money-payment 결제하기 → niceepay 비번 팝업
        log("money '결제하기' 클릭...")
        money_page.locator(
            "button.button--primary.button--large.button--block"
        ).first.click(timeout=8000)

        # niceepay PIN 페이지(팝업) 대기
        log("NICE Pay 비번 화면 대기...")
        pin_page = None
        for _ in range(30):
            for pg in ctx.pages:
                if "niceepay" in pg.url or "pinCert" in pg.url:
                    pin_page = pg
                    break
            if pin_page:
                break
            time.sleep(0.5)
        if not pin_page:
            raise RuntimeError("NICE Pay 비번 화면을 찾지 못했습니다.")

        # 7~8) 비번 입력 + 완료
        enter_pin(pin_page, args.pin)
        time.sleep(3)
        shot(page, "after_pay")
        print("\n✅ [full 단계] 결제 시도 완료. 화면(after_pay.png)에서 결과 확인하세요.")
        input("확인 후 Enter로 종료 ▶ ")
        ctx.close()


if __name__ == "__main__":
    main()
