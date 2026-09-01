# -*- coding: utf-8 -*-
import sys, os, time, json, re, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
import urllib.request
req = urllib.request.Request("http://127.0.0.1:9223/json/new?https://www.youtube.com/watch%3Fv%3D4uYIsLN9Nyg", method="PUT")
tab = json.loads(urllib.request.urlopen(req, timeout=10).read())["id"]
time.sleep(10)
c = CDPConn(tab); c.call("Runtime.enable")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True, "awaitPromise": True})
    res = r.get("result", {})
    if "exceptionDetails" in res: return "EXC " + str(res["exceptionDetails"].get("text"))[:100]
    return res.get("result", {}).get("value")
title = js("document.title")
print("제목:", title)
# 캡션 트랙 URL 추출
cap = js("""(function(){try{var p=ytInitialPlayerResponse;var t=p.captions.playerCaptionsTracklistRenderer.captionTracks;return JSON.stringify(t.map(x=>({lang:x.languageCode,url:x.baseUrl.slice(0,300)})));}catch(e){return 'ERR:'+e.message;}})()""")
print("캡션:", (cap or "")[:400])
if cap and cap.startswith("["):
    tracks = json.loads(cap)
    ko = next((t for t in tracks if t["lang"].startswith("ko")), tracks[0] if tracks else None)
    if ko:
        txt = js(f"""(async()=>{{var r=await fetch({json.dumps(ko['url'])}+'&fmt=json3');var j=await r.json();
          return j.events.filter(e=>e.segs).map(e=>e.segs.map(s=>s.utf8).join('')).join(' ');}})()""")
        open("C:/tmp/yt_transcript.txt","w",encoding="utf-8").write(txt or "")
        print("자막길이:", len(txt or ""))
# 설명
desc = js("""(function(){try{return ytInitialPlayerResponse.videoDetails.shortDescription.slice(0,500);}catch(e){return ''}})()""")
print("설명:", (desc or "")[:300])
c.close()
