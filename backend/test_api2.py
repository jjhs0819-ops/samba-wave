"""무신사 JS에서 api2 경로 추출."""

import httpx
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

js_urls = [
    ("ranking.js", "https://static.msscdn.net/static/v2/pc/ranking/ranking.js"),
    ("vendor.js", "https://static.msscdn.net/static/v2/pc/ranking/vendor.js"),
]

for label, url in js_urls:
    try:
        r = httpx.get(url, headers=headers, timeout=15.0)
        js = r.text
        # api2 경로
        api2 = re.findall(r"api2/[\w/.-]{3,80}", js)
        if api2:
            print(f"\n{label} api2 경로:")
            for p in sorted(set(api2)):
                print(f"  {p}")
        # /dp/ 경로
        dp = re.findall(r"/dp/[\w/.-]{3,80}", js)
        if dp:
            print(f"{label} /dp/ 경로:")
            for p in sorted(set(dp)):
                print(f"  {p}")
        # ranking 근처에서 URL 조합 힌트
        for m in list(re.finditer(r"archive", js))[:3]:
            s = max(0, m.start() - 300)
            e = min(len(js), m.end() + 300)
            ctx = js[s:e]
            # URL 패턴 찾기
            url_frags = re.findall(r'"(/[^"]{5,60})"', ctx)
            if url_frags:
                print(f"\n{label} archive 근처 URL:")
                for f in url_frags:
                    print(f"  {f}")
    except Exception as ex:
        print(f"{label}: {ex}")

# ranking.js에서 ea 클라이언트 (api.musinsa.com) 호출 패턴
r = httpx.get(js_urls[0][1], headers=headers, timeout=15.0)
js = r.text
# ea( 또는 ea. 뒤에 오는 패턴
ea_calls = re.findall(r'ea[.(]\s*[{"]([^"}{]{3,100})', js)
if ea_calls:
    print("\nea 클라이언트 호출:")
    for c in sorted(set(ea_calls)):
        print(f"  {c}")
