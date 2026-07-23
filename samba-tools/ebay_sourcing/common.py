"""번장→eBay 소싱 공통 상수·헬퍼.

호스트(웨일/DB 직접) 스크립트에서 import. 컨테이너 스크립트는 backend 모듈 사용.
"""

import io
import json
import sys
import time
import urllib.request

# ── 상수 (검증됨 2026-07-21) ──
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"  # K-TCG Vault = 캐논리츠 = seller byunggi
TA = "ma_01KWVPQYKN4RRMVRKBF4DYV069"  # TCG Authenticore = 마늘 (marketing 미승인)
TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
POLICY = "pol_01KXD2K5JE2HHR53GZ1NGV0PGV"  # eBay 정책(adEnabled/adRate)
CAT_SINGLE = "183454"  # TCG 싱글카드
CAT_LOT = "183455"  # 복수장 묶음(자동화 비권장)
DB_DSN = "postgresql://samba:09aac90f3fb8c4394ad2d6062b1a5910@127.0.0.1:5432/samba"
CDP = "http://localhost:9223"

# 번장 제외 키워드 (구매글/일괄/등급)
BAD_KW = [
    "일괄", "세트", "삽니다", "매입", "구해", "구합", "구매", "psa",
    "묶음", "한꺼번에", "팝니다만", "일판",  # 일판=일본판(한판 리스팅과 다름)
]


def utf8_stdout():
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )


def _whale_tab():
    """번장 탭 재사용 — 기존 m.bunjang.co.kr 탭 있으면 그거, 없으면 1개만 새로.

    매번 새 탭 열면 브라우저에 탭 수십개 쌓임(2026-07-22 사용자 지적). 재사용 필수.
    """
    tabs = json.loads(urllib.request.urlopen(CDP + "/json", timeout=5).read())
    for t in tabs:
        if t.get("type") == "page" and "bunjang.co.kr" in t.get("url", ""):
            return t["webSocketDebuggerUrl"]
    new = json.loads(
        urllib.request.urlopen(
            urllib.request.Request(
                CDP + "/json/new?https://m.bunjang.co.kr/", method="PUT"
            ),
            timeout=5,
        ).read()
    )
    return new["webSocketDebuggerUrl"]


class Whale:
    """웨일 CDP in-tab fetch (번장 same-origin 우회). with 블록으로 사용."""

    def __init__(self):
        import websocket

        self.ws = websocket.create_connection(
            _whale_tab(), timeout=60, suppress_origin=True
        )
        self._id = 0
        self._cmd("Runtime.enable")
        time.sleep(2)

    def _cmd(self, method, params=None):
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self._id:
                return m

    def fetch_json(self, url):
        """번장 오리진에서 fetch → dict (실패 시 {'_err':...})."""
        js = (
            "(async()=>{try{const r=await fetch(%r);"
            "if(!r.ok)return JSON.stringify({_err:'HTTP'+r.status});"
            "return await r.text();}catch(e){return JSON.stringify({_err:'ERR'})}})()"
            % url
        )
        r = self._cmd(
            "Runtime.evaluate",
            {"expression": js, "awaitPromise": True, "returnByValue": True},
        )
        v = r.get("result", {}).get("result", {}).get("value", "")
        try:
            return json.loads(v)
        except Exception:
            return {"_err": v[:80]}

    def product(self, pid):
        """번장 상품 상세 → product dict (name/price/qty/saleStatus/imageUrl/imageCount/description)."""
        d = self.fetch_json(
            f"https://api.bunjang.co.kr/api/pms/v3/products-detail/{pid}?viewerUid=-1"
        )
        if d.get("_err"):
            return d
        return d.get("data", {}).get("product", {})

    def search(self, keyword, n=40):
        """번장 키워드 검색 → list (find_v2)."""
        import urllib.parse as up

        d = self.fetch_json(
            "https://api.bunjang.co.kr/api/1/find_v2.json?q="
            + up.quote(keyword)
            + f"&order=score&page=0&n={n}&req_ref=search&stat_device=w&version=5"
        )
        return d.get("list", []) if not d.get("_err") else []

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def img_url(template, cnt=1, res=800):
    """번장 imageUrl 템플릿({cnt}/{res}) → 실제 URL."""
    return template.replace("{cnt}", str(cnt)).replace("{res}", str(res))


# 크림 구매 부대비용 — 표시가 외에 배송비 + 구매수수료가 실제로 나간다.
# 이걸 빼고 표시가만 원가로 잡으면 판매가가 그만큼 덜 붙어 마진이 깎인다.
# (2026-07-23 확인: BTS 응원봉 ₩77,000 표시가로 등록 → 실매입 ₩84,541)
KREAM_SHIPPING_FEE = 5000  # 건당 배송비
KREAM_FEE_RATE = 0.033  # 구매금액 대비 수수료 3.3%


def kream_real_cost(display_price) -> float:
    """크림 표시가 → 실제 매입원가(배송비 + 수수료 포함)."""
    p = float(display_price or 0)
    if p <= 0:
        return 0.0
    return round(p + KREAM_SHIPPING_FEE + p * KREAM_FEE_RATE)
