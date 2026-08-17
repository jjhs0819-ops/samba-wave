# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Runtime.enable")
def js(e, aw=True):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True, "awaitPromise": aw})
    res = r.get("result", {})
    if "exceptionDetails" in res:
        return "EXC: " + str(res["exceptionDetails"].get("text"))[:120]
    return res.get("result", {}).get("value")
print("big imgs:", js("[...document.querySelectorAll('img')].filter(i=>i.getBoundingClientRect().width>=300).length", False))
print("src:", js("(function(){var a=[...document.querySelectorAll('img')].filter(i=>i.getBoundingClientRect().width>=300);return a.length?a[a.length-1].src.slice(0,60):'NONE';})()", False))
print("fetch test:", js("(async()=>{try{var a=[...document.querySelectorAll('img')].filter(i=>i.getBoundingClientRect().width>=300);if(!a.length)return 'NOIMG';var r=await fetch(a[a.length-1].src);var b=await r.arrayBuffer();return 'BYTES='+b.byteLength;}catch(e){return 'ERR='+e.message;}})()"))
print("canvas test:", js("(function(){try{var a=[...document.querySelectorAll('img')].filter(i=>i.getBoundingClientRect().width>=300);if(!a.length)return 'NOIMG';var im=a[a.length-1];var cv=document.createElement('canvas');cv.width=im.naturalWidth;cv.height=im.naturalHeight;cv.getContext('2d').drawImage(im,0,0);return 'LEN='+cv.toDataURL('image/png').length;}catch(e){return 'ERR='+e.message;}})()", False))
c.close()
