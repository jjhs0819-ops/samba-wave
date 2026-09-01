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
# [확정 프롬프트 — 절대 수정 금지. 2026-08-18 사용자 확정, 08-19 카드폭=포스트잇폭 추가]
# 비율 문구 없으면 카드가 세로로 눌리고, 꽉채움 문구 없으면 액자처럼 축소된다.
PROMPT = (
    "첫번째 사진에서 카드만 두번째 카드로 바꿔줘. "
    "나머지(책상 질감, 포스트잇 위치와 글씨, 조명, 그림자, 카드 각도와 위치)는 첫번째 사진 그대로 유지해. "
    "카드는 실물 트레이딩카드 규격 63mm x 88mm 비율(가로:세로 = 1 : 1.4)을 정확히 지켜줘. "
    "세로로 눌리거나 가로로 늘어나면 안 되고, 첫번째 사진의 카드와 같은 크기·같은 비율이어야 해. "
    "결과는 정사각형 1:1 이미지이고, 나무 책상이 화면 전체를 꽉 채워야 해. "
    "가장자리에 여백·테두리·액자 효과를 넣지 말고, 첫번째 사진과 똑같은 화각으로 만들어줘."
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
    subprocess.run(
        ["pwsh", "-NoProfile", "-Command", ps],
        capture_output=True, timeout=60, creationflags=0x08000000,  # 창 팝업 방지
    )


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


# [2026-08-29] 첨부 비우기는 시작뿐 아니라 **모든 종료 경로**에서 해야 한다.
# 실패로 빠져나갈 때 안 비우면 첨부가 그대로 남아 다음 건에 이월된다.
# 실측: 실패 16건이 누적돼 입력창에 사진 10장이 쌓여 있었다(2026-08-29).
def clear_attachments(c, rounds=40):
    """입력창의 첨부를 전부 제거. 남은 개수를 돌려준다."""
    for _ in range(rounds):
        n = js(
            c,
            "(function(){var b=[...document.querySelectorAll('button')]"
            ".filter(x=>/첨부파일 닫기|첨부 닫기/i.test(x.getAttribute('aria-label')||'')"
            "&&x.getBoundingClientRect().width>0);"
            "if(!b.length)return 0;b[0].click();return 1;})()",
        )
        if not n:
            break
        time.sleep(0.6)
    return js(
        c,
        "[...document.querySelectorAll('button')].filter(x=>"
        "/첨부파일 닫기|첨부 닫기/i.test(x.getAttribute('aria-label')||'')"
        "&&x.getBoundingClientRect().width>0).length",
    )


def main():
    card_path, out_path = sys.argv[1], sys.argv[2]
    tab_id = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_TAB

    c = CDPConn(tab_id)
    c.call("Page.enable")
    c.call("Runtime.enable")
    c.call("Page.bringToFront")

    # [2026-08-20 방침 확정] 같은 탭 안에서 '건당 새 채팅'.
    # 한 채팅 연속 사용은 첨부 누적·혼합, 포스트잇 누락, 직전 카드 재생성 등
    # 오염 사고가 반복됨(실측 다수). 탭은 절대 늘리지 않는다.
    js(
        c,
        "(function(){var b=[...document.querySelectorAll('button,a')]"
        ".filter(x=>/새 채팅|New chat/i.test((x.innerText||'')+(x.getAttribute('aria-label')||''))"
        "&&x.getBoundingClientRect().width>0);"
        "if(b.length){b[0].click();return true;}return false;})()",
    )
    time.sleep(4)

    # [최우선] 새 채팅으로 전환해도 입력창의 첨부는 그대로 유지된다(실측 2026-08-20).
    # 시작 시 반드시 첨부·텍스트를 전부 비운다. 안 비우면 이전 건의 첨부가 이월·누적돼
    # 여러 카드가 한 요청에 섞이고, 첨부 개수 검증도 잔여물 때문에 헛통과한다.
    clear_attachments(c)
    js(
        c,
        "(function(){var e=document.querySelector('[contenteditable=\"true\"]');"
        "if(e){e.focus();e.innerText='';e.dispatchEvent(new InputEvent('input',{bubbles:true}));}})()",
    )
    time.sleep(0.5)

    # 입력창 포커스
    js(c, "(function(){var e=document.querySelector('[contenteditable=\"true\"]'); if(e){e.focus();} return !!e;})()")
    time.sleep(0.5)

    # 사진 2장 순서대로 붙여넣기 — [최우선] 붙여넣기 성공을 매번 검증한다.
    # 클립보드 복사/붙여넣기가 조용히 실패하면 프롬프트만 전송되고, 제미나이가
    # 직전 맥락의 카드를 새로 생성해 15건이 전부 릴리에로 오염된 사고(2026-08-20).
    ATTACH_CNT = (
        "[...document.querySelectorAll('button')].filter(x=>"
        "/첨부파일 닫기|첨부 닫기/i.test(x.getAttribute('aria-label')||'')"
        "&&x.getBoundingClientRect().width>0).length"
    )
    for idx, p in enumerate((REF, normalize(card_path)), 1):
        attached = False
        for attempt in range(3):
            set_clipboard_image(p)
            time.sleep(0.8)
            js(c, "(function(){var e=document.querySelector('[contenteditable=\"true\"]'); if(e){e.focus();} })()")
            paste(c)
            # 업로드 완료 = 첨부 개수가 idx 에 도달할 때까지 대기(최대 20초)
            for _ in range(10):
                time.sleep(2)
                if (js(c, ATTACH_CNT) or 0) >= idx:
                    attached = True
                    break
            if attached:
                break
            print(f"  ..붙여넣기 재시도 {idx}번째 사진 (시도 {attempt + 1})", flush=True)
        if not attached:
            print(f"FAIL PASTE {idx}번째 사진 첨부 실패 — 전송 중단")
            clear_attachments(c)
            c.close()
            sys.exit(3)

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
    # [중요] 기준선은 '개수'가 아니라 'src 집합'이다.
    # 개수 기준은 스크롤/레이아웃으로 렌더 폭이 흔들리면 새 이미지 없이도 증가해,
    # 직전 카드의 사진을 새 결과로 오인해 집어간다(2026-08-19 실측: 서로 다른
    # 카드 11쌍이 같은 사진으로 등록되는 사고).
    before_srcs = js(c, "JSON.stringify([...document.querySelectorAll('img')].map(i=>i.src).filter(s=>s.startsWith('blob:')))") or "[]"
    import json as _json
    before_set = set(_json.loads(before_srcs))
    for t in ("keyDown", "keyUp"):
        c.call(
            "Input.dispatchKeyEvent",
            {"type": t, "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13},
        )

    # 결과 이미지 생성 대기 — 웹앱은 API보다 훨씬 느리고 편차가 크다.
    # 실측: 보통 1~5분, 혼잡할 땐 15분 초과. 짧게 잡으면 멀쩡한 생성을 버리게 된다.
    new_src = None
    deadline = time.time() + 1500
    while time.time() < deadline:
        js(c, "window.scrollTo(0, document.body.scrollHeight)")
        cur = _json.loads(js(
            c,
            "JSON.stringify([...document.querySelectorAll('img')]"
            ".filter(i=>i.src.startsWith('blob:')&&i.getBoundingClientRect().width>=300)"
            ".map(i=>i.src))",
        ) or "[]")
        fresh = [s for s in cur if s not in before_set]
        if fresh:
            new_src = fresh[-1]
            time.sleep(3)  # 렌더 안정화
            break
        tail = js(c, "document.body.innerText.slice(-400)") or ""
        if "이미지를 생성할 수 없" in tail:
            print("FAIL LIMIT 일일 이미지 한도 소진")
            clear_attachments(c)
            c.close()
            sys.exit(2)
        time.sleep(2)
    else:
        print("FAIL 생성 타임아웃")
        clear_attachments(c)
        c.close()
        sys.exit(1)

    # 결과 이미지 바이트 회수 — canvas.toDataURL 방식.
    # [중요] 왜 canvas 인가:
    #   - UI 다운로드 메뉴 클릭: 버튼이 호버/포커스 때만 뜨고 aria-label 이 자주 바뀜 → 불안정
    #   - fetch(blob:): CSP 에 막혀 'Failed to fetch'
    #   - canvas: 결과 img 의 src 가 blob:(동일 출처)라 캔버스가 오염되지 않아 통과한다.
    #     (과거 실패했던 건 src 가 lh3.googleusercontent.com 인 교차출처 케이스였다)
    # 반드시 '이번에 새로 생긴 src' 그 요소만 캡처한다 (마지막 요소 X)
    data_url = None
    for _ in range(45):
        data_url = js(
            c,
            "(function(s){try{var im=[...document.querySelectorAll('img')].find(i=>i.src===s);"
            "if(!im||!im.complete||im.naturalWidth<512)return null;"
            "var cv=document.createElement('canvas');"
            "cv.width=im.naturalWidth;cv.height=im.naturalHeight;"
            "cv.getContext('2d').drawImage(im,0,0);"
            "return cv.toDataURL('image/png');}catch(e){return 'ERR:'+e.message;}})"
            f"({_json.dumps(new_src)})",
        )
        if data_url and data_url.startswith("data:image"):
            break
        time.sleep(2)

    if not data_url or not data_url.startswith("data:image"):
        print(f"FAIL 결과 이미지 회수 실패 ({str(data_url)[:60]})")
        clear_attachments(c)
        c.close()
        sys.exit(1)

    with open(out_path, "wb") as f:
        f.write(base64.b64decode(data_url.split(",", 1)[1]))
    print(f"OK {os.path.getsize(out_path)} bytes -> {out_path}")
    c.close()


if __name__ == "__main__":
    main()
