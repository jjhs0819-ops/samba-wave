# -*- coding: utf-8 -*-
"""진행 중인 생성이 끝날 때까지 기다렸다가 결과 이미지를 canvas로 회수."""
import sys, os, time, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
BIG = ("[...document.querySelectorAll('img')].filter(i=>"
       "i.getBoundingClientRect().width>=300||/AI로 생성|generated/i.test(i.alt||''))")
c = CDPConn(sys.argv[1]); c.call("Runtime.enable")
out = sys.argv[2]
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True, "awaitPromise": True})
    return r.get("result", {}).get("result", {}).get("value")
dl = None
for i in range(180):
    d = js("(function(){try{var a=" + BIG + ";if(!a.length)return null;var im=a[a.length-1];"
           "if(!im.naturalWidth)return null;var cv=document.createElement('canvas');"
           "cv.width=im.naturalWidth;cv.height=im.naturalHeight;cv.getContext('2d').drawImage(im,0,0);"
           "return cv.toDataURL('image/png');}catch(e){return 'ERR:'+e.message;}})()")
    if d and str(d).startswith("data:image"):
        dl = d; break
    time.sleep(5)
if not dl:
    print("FAIL 회수 실패"); c.close(); sys.exit(1)
open(out, "wb").write(base64.b64decode(dl.split(",",1)[1]))
print("OK", os.path.getsize(out), "->", out)
c.close()
