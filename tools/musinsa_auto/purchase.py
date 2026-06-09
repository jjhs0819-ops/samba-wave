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


def _find_page(ctx, substr, timeout=15):
    """ctx의 열린 페이지 중 URL에 substr 포함된 페이지를 기다려 반환."""
    end = time.time() + timeout
    while time.time() < end:
        for pg in list(ctx.pages):
            try:
                if substr in pg.url:
                    return pg
            except Exception:
                pass
        time.sleep(0.3)
    return None


# 주소폼 Vue 인스턴스에 값을 채우는 JS (무신사 자체 함수 findAddressComplete 활용)
FILL_ADDR_JS = r"""
(c) => {
  const root = document.querySelector('#commonLayoutContents');
  const vm = root && root.__vue__;
  if (!vm || !vm.form) return 'NO_VUE';
  vm.form.name = c.name;
  vm.form.mobile = c.phone;
  if (typeof vm.findAddressComplete === 'function') {
    vm.findAddressComplete({ zipcode: c.postal, address1: c.addr });
  } else {
    vm.form.zipcode = c.postal;
    vm.form.address1 = c.addr;
  }
  vm.form.address2 = c.addr2;
  if (c.memo) {
    const presets = (vm.ui && vm.ui.additionalMessageType) || [];
    if (presets.includes(c.memo)) {
      vm.form.additionalMessage = c.memo;
    } else {
      vm.form.additionalMessage = '직접입력';
      vm.form.additionalMessageManual = c.memo;
    }
  }
  return 'OK:' + JSON.stringify({
    name: vm.form.name, mobile: vm.form.mobile,
    zipcode: vm.form.zipcode, address1: vm.form.address1, address2: vm.form.address2,
  });
}
"""


def set_address(ctx, order_page, c: dict) -> None:
    """주문서에서 고객 배송지를 입력/선택한다.

    전략: 비-기본 배송지 슬롯을 재사용(수정)해 고객정보로 덮어쓰고 선택.
    (기본 배송지는 건드리지 않는다.) 비-기본 슬롯이 없으면 '배송지 추가하기'.
    """
    log("🚚 배송지 변경 클릭...")
    order_page.wait_for_timeout(800)
    # 배송지 변경은 새 윈도우(팝업)로 열린다 → expect_page 로 직접 캐치
    lst = None
    try:
        with ctx.expect_page(timeout=15000) as pinfo:
            order_page.get_by_text("배송지 변경").first.click(timeout=8000)
        lst = pinfo.value
        lst.wait_for_load_state("domcontentloaded")
    except Exception as e:
        log(f"expect_page 실패({e}) — 열린 페이지 스캔 시도")
        lst = _find_page(ctx, "/addresses/order", 6)
    if not lst:
        log(f"현재 열린 페이지들: {[p.url for p in ctx.pages]}")
        raise RuntimeError("배송지 목록 팝업을 찾지 못했습니다.")
    if "/addresses/order" not in lst.url:
        _wait_url_contains(lst, "/addresses/order", 8)
    log(f"배송지 팝업 열림: {lst.url[:60]}")
    lst.wait_for_timeout(1800)

    # 비-기본(삭제 버튼 있는) 항목의 '수정' 진입, 없으면 추가
    edit_btn = lst.locator(
        ".order-address-item:has(button:has-text('삭제')) button:has-text('수정')"
    )
    if edit_btn.count() > 0:
        log("기존 비기본 배송지 슬롯 '수정' 진입(덮어쓰기)")
        edit_btn.first.click()
        if not _wait_url_contains(lst, "/addresses/update/", 15):
            log(f"(현재 URL: {lst.url})")
    else:
        log("'배송지 추가하기' 진입")
        lst.locator("a.order-address-item__add").first.click()
        if not _wait_url_contains(lst, "/addresses/add", 15):
            log(f"(현재 URL: {lst.url})")
    lst.wait_for_timeout(1800)

    # Vue form 채우기
    res = lst.evaluate(FILL_ADDR_JS, c)
    log(f"폼 채움 결과: {res}")
    if res == "NO_VUE":
        shot(lst, "addr_no_vue")
        raise RuntimeError("주소폼 Vue 인스턴스 접근 실패(__vue__). 화면 확인 필요.")
    lst.wait_for_timeout(800)
    shot(lst, "addr_filled")

    # 저장(formSubmit)
    log("주소 저장(formSubmit)...")
    lst.evaluate(
        "() => { const vm=document.querySelector('#commonLayoutContents').__vue__; vm.formSubmit(); }"
    )
    # 저장 성공 시 목록으로 복귀
    if not _wait_url_contains(lst, "/addresses/order", 15):
        log(f"(저장 후 URL: {lst.url}) — 검증 실패했을 수 있음")
        shot(lst, "addr_after_submit")
    lst.wait_for_timeout(1500)

    # 방금 저장한 고객 주소 선택 + 변경하기
    log(f"'{c['name']}' 배송지 선택...")
    try:
        lst.locator(f".order-address-item__information:has-text(\"{c['name']}\")").first.click(timeout=5000)
    except Exception:
        log("이름으로 항목 클릭 실패 — 첫 항목 라디오 시도")
    lst.wait_for_timeout(500)
    lst.locator(".page-button button").first.click(timeout=5000)  # 변경하기
    log("변경하기 클릭 — 주문서로 복귀")
    order_page.wait_for_timeout(2500)


def _wait_url_contains(page, substr, timeout=15) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if substr in page.url:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--size", required=True, help="선택할 사이즈 (예: L)")
    ap.add_argument("--stage", choices=["order", "pay", "full"], default="order")
    ap.add_argument("--max", type=int, default=150000, help="최대 결제 허용 금액(원)")
    ap.add_argument("--pin", default=os.environ.get("MUSINSA_PIN", ""),
                    help="결제 비밀번호 (기본: 환경변수 MUSINSA_PIN)")
    # 고객 배송지 (지정 시 주소 자동입력 수행)
    ap.add_argument("--name", help="받는분 이름")
    ap.add_argument("--phone", help="연락처 (010-XXXX-XXXX)")
    ap.add_argument("--postal", help="우편번호 (5자리)")
    ap.add_argument("--addr", help="기본주소(도로명)")
    ap.add_argument("--addr2", help="상세주소")
    ap.add_argument("--memo", default="", help="배송 메모")
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

        # 고객 배송지 자동입력 (--name 지정 시)
        if args.name:
            customer = {
                "name": args.name, "phone": args.phone, "postal": args.postal,
                "addr": args.addr, "addr2": args.addr2, "memo": args.memo,
            }
            set_address(ctx, page, customer)
            shot(page, "order_form_with_address")

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
