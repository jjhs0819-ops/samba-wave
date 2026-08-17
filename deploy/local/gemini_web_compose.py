# -*- coding: utf-8 -*-
"""브라우저 제미나이(웨일 CDP)로 포스트잇 합성사진 생성 — API 과금 0원.

건당 절차:
  새 채팅 → 레퍼런스 사진 붙여넣기 → 새 카드 사진 붙여넣기 → 프롬프트 전송
  → 생성 완료 대기 → 우클릭 메뉴 '이미지 다운로드' → Downloads 새 파일 회수

사용:
  python3 gemini_web_compose.py <카드이미지경로> <출력경로> [탭ID]
"""

import base64
import glob
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn  # noqa: E402

# [중요] EXIF 회전값이 박힌 원본을 쓰면 클립보드 경로에서 눕혀진 픽셀이 그대로 들어가
# 결과물도 옆으로 눕는다. 픽셀 자체를 세워 저장한 파일을 쓴다.
REF = "C:/tmp/ref_upright.jpg"
DOWNLOADS = "C:/Users/canno/Downloads"
PROMPT = (
    "첫번째 사진에서 카드만 두번째 카드로 바꿔줘. "
    "나머지(책상 질감, 포스트잇 위치와 글씨, 조명, 그림자, 카드 각도와 위치)는 첫번째 사진 그대로 유지해."
)
DEFAULT_TAB = "88C17EECB892F607421395A19075CFBD"


def normalize(path):
    """EXIF 회전 반영 + RGB 로 눕힘 없는 임시 JPG 생성."""
    from PIL import Image, ImageOps

    im = ImageOps.exif_transpose(Image.open(path))
    if im.mode in ("RGBA", "LA", "P"):
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        im = bg
    elif im.mode != "RGB":
        im = im.convert("RGB")
    tmp = os.path.join("C:/tmp", "_clip_%d.jpg" % (abs(hash(path)) % 10**8))
    im.save(tmp, quality=95)
    return tmp


def set_clipboard_image(path):
    """윈도우 클립보드에 이미지 올리기 (pwsh)."""
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
        f"$i=[System.Drawing.Image]::FromFile('{path}'); "
        "[System.Windows.Forms.Clipboard]::SetImage($i); $i.Dispose()"
    )
    subprocess.run(["pwsh", "-NoProfile", "-Command", ps], capture_output=True, timeout=60)


def newest_download(before):
    """Downloads 폴더에서 새로 생긴 이미지 파일 반환."""
    for _ in range(60):
        files = set(glob.glob(os.path.join(DOWNLOADS, "*")))
        new = [f for f in files - before if not f.endswith(".crdownload")]
        # .tmp 로 떨어지는 경우도 포함 (제미나이 다운로드 특성)
        cand = [f for f in new if os.path.getsize(f) > 100_000]
        if cand:
            time.sleep(1)  # 쓰기 완료 대기
            return max(cand, key=os.path.getmtime)
        time.sleep(1)
    return None


def js(c, expr):
    r = c.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
    return r.get("result", {}).get("result", {}).get("value")


def paste(c):
    """Ctrl+V 키 이벤트 전송."""
    for t, key in (("keyDown", 1), ("keyUp", 0)):
        c.call(
            "Input.dispatchKeyEvent",
            {
                "type": t,
                "modifiers": 2,  # Ctrl
                "key": "v",
                "code": "KeyV",
                "windowsVirtualKeyCode": 86,
                "nativeVirtualKeyCode": 86,
            },
        )
    time.sleep(0.3)


# 결과 이미지 판별 — 첨부 썸네일도 naturalWidth 는 1024라 그걸로는 구분 안 된다.
# 실제 렌더 폭이 다르다(썸네일 112px / 결과 708px). alt 에 'AI로 생성'도 붙는다.
BIG_IMG_JS = (
    "[...document.querySelectorAll('img')].filter(i=>"
    "i.getBoundingClientRect().width>=300||/AI로 생성|generated/i.test(i.alt||''))"
)


def count_imgs(c):
    """생성 결과 이미지 개수. 첨부 썸네일은 렌더 폭이 작아 제외됨."""
    return js(c, f"{BIG_IMG_JS}.length") or 0


def main():
    card_path, out_path = sys.argv[1], sys.argv[2]
    tab_id = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_TAB

    c = CDPConn(tab_id)
    c.call("Page.enable")
    c.call("Runtime.enable")
    c.call("Page.bringToFront")

    # [중요] 새 채팅을 만들지 않는다.
    # 건당 '새 채팅'을 누르면 대화 목록이 수백 개로 불어나 사용자의 기존 기록이 밀려난다.
    # 대신 지금 열려 있는 한 채팅 안에서 계속 이어 붙이고, 생성 완료 판정은
    # '전송 직전 이미지 개수' 를 기준선으로 삼아 증가를 감지하는 방식으로 처리한다.

    # 입력창 포커스
    js(c, "(function(){var e=document.querySelector('[contenteditable=\"true\"]'); if(e){e.focus();} return !!e;})()")
    time.sleep(0.5)

    # 사진 2장 순서대로 붙여넣기
    for p in (REF, normalize(card_path)):
        set_clipboard_image(p)
        time.sleep(0.8)
        js(c, "(function(){var e=document.querySelector('[contenteditable=\"true\"]'); if(e){e.focus();} })()")
        paste(c)
        time.sleep(4)  # 업로드 대기

    # 프롬프트 입력 + 전송
    safe = PROMPT.replace("'", "\\'")
    js(
        c,
        "(function(t){var e=document.querySelector('[contenteditable=\"true\"]');"
        "e.focus();document.execCommand('insertText',false,t);return e.innerText;})"
        f"('{safe}')",
    )
    time.sleep(1)
    # 한 채팅을 계속 쓰므로 항상 맨 아래를 보고 있어야 새 결과가 렌더된다
    js(c, "window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(0.5)
    before_imgs = count_imgs(c)  # 전송 직전 기준선 (첨부 썸네일 제외된 값)
    for t in ("keyDown", "keyUp"):
        c.call(
            "Input.dispatchKeyEvent",
            {"type": t, "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13},
        )

    # 결과 이미지 생성 대기 — 웹앱은 API보다 훨씬 느리고 편차가 크다.
    # 실측: 보통 1~5분, 혼잡할 땐 15분 초과. 짧게 잡으면 멀쩡한 생성을 버리게 된다.
    deadline = time.time() + 1500
    while time.time() < deadline:
        js(c, "window.scrollTo(0, document.body.scrollHeight)")
        if count_imgs(c) > before_imgs:
            time.sleep(3)  # 렌더 안정화
            break
        time.sleep(2)
    else:
        print("FAIL 생성 타임아웃")
        c.close()
        sys.exit(1)

    # 결과 이미지 바이트 회수 — canvas.toDataURL 방식.
    # [중요] 왜 canvas 인가:
    #   - UI 다운로드 메뉴 클릭: 버튼이 호버/포커스 때만 뜨고 aria-label 이 자주 바뀜 → 불안정
    #   - fetch(blob:): CSP 에 막혀 'Failed to fetch'
    #   - canvas: 결과 img 의 src 가 blob:(동일 출처)라 캔버스가 오염되지 않아 통과한다.
    #     (과거 실패했던 건 src 가 lh3.googleusercontent.com 인 교차출처 케이스였다)
    data_url = None
    for _ in range(45):
        data_url = js(
            c,
            "(function(){try{var a=(" + BIG_IMG_JS + ")"
            # 아직 디코딩 안 된 자리표시 이미지를 잡으면 캔버스가 null 을 뱉는다.
            # 실제로 로드가 끝난 것만 후보로 남긴다.
            ".filter(i=>i.complete&&i.naturalWidth>=512);"
            "if(!a.length)return null;var im=a[a.length-1];"
            "var cv=document.createElement('canvas');"
            "cv.width=im.naturalWidth;cv.height=im.naturalHeight;"
            "cv.getContext('2d').drawImage(im,0,0);"
            "return cv.toDataURL('image/png');}catch(e){return 'ERR:'+e.message;}})()",
        )
        if data_url and data_url.startswith("data:image"):
            break
        time.sleep(2)

    if not data_url or not data_url.startswith("data:image"):
        print(f"FAIL 결과 이미지 회수 실패 ({str(data_url)[:60]})")
        c.close()
        sys.exit(1)

    with open(out_path, "wb") as f:
        f.write(base64.b64decode(data_url.split(",", 1)[1]))
    print(f"OK {os.path.getsize(out_path)} bytes -> {out_path}")
    c.close()


if __name__ == "__main__":
    main()
