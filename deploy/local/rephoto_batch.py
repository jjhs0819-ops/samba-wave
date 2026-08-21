# -*- coding: utf-8 -*-
"""오늘 등록분 사진 전량 재생성·교체 [호스트 실행].

사진 밀림 사고(2026-08-19) 수습: 각 상품의 올바른 크림 카드 이미지로
합성사진을 다시 만들어 기존 리스팅에 revise 로 교체한다. 삭제·신규등록 없음.

사용: python3 rephoto_batch.py <pid목록파일> <제미나이탭ID>
"""

import hashlib
import io
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
CONTAINER = "local-samba-api-1"
PY = "/app/backend/.venv/bin/python3"
WORK = "C:/tmp/rephoto"


def sh(args, timeout=1500):
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    r = subprocess.run(args, capture_output=True, timeout=timeout, env=env, creationflags=0x08000000)
    return (r.stdout or b"").decode("utf-8", "replace"), (r.stderr or b"").decode("utf-8", "replace")


def md5(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


def main():
    pid_file, tab = sys.argv[1], sys.argv[2]
    pids = [l.strip() for l in open(pid_file, encoding="utf-8") if l.strip()]
    os.makedirs(WORK, exist_ok=True)
    print(f"대상 {len(pids)}건", flush=True)

    prev_md5 = ""
    ok = fail = 0
    for pid in pids:
        try:
            # 크림에서 올바른 카드 이미지 URL 재조회
            out, _ = sh(["docker", "exec", CONTAINER, PY, "/tmp/kream_probe_one.py", pid], 240)
            line = [x for x in out.splitlines() if x.startswith("RESULT ")]
            info = json.loads(line[0][7:]) if line else {}
            img_url = info.get("img_url")
            if not img_url:
                # 이미 등록됨이면 probe 가 차단 — 원본 URL 을 DB에서
                out2, _ = sh(["docker", "exec", CONTAINER, PY, "-c", (
                    "import asyncio,sys;sys.path.insert(0,'/app/backend')\n"
                    "async def m():\n"
                    " import backend.main\n"
                    " from backend.core.tenant_context import current_tenant_id\n"
                    " from backend.db.orm import get_write_session\n"
                    " from backend.domain.samba.account.model import SambaMarketAccount\n"
                    " from backend.domain.samba.proxy.kream import KreamPartnerClient\n"
                    " from sqlmodel import select\n"
                    " tok=current_tenant_id.set('tn_01KRX6H1Q97JGPXRPB011985QT')\n"
                    " async with get_write_session() as s:\n"
                    "  ka=(await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.market_type=='kream'))).scalars().first()\n"
                    "  e=ka.additional_fields if isinstance(ka.additional_fields,dict) else {}\n"
                    "  k=KreamPartnerClient(str(e.get('apiService') or ''),str(e.get('apiKey') or ka.api_key or ''),str(e.get('apiSecret') or ka.api_secret or ''))\n"
                    f"  c,b=await k.get_product({pid})\n"
                    "  print('IMGURL',(b.get('main_images') or [''])[0])\n"
                    " current_tenant_id.reset(tok)\n"
                    "asyncio.run(m())"
                )], 240)
                m = [x for x in out2.splitlines() if x.startswith("IMGURL ")]
                img_url = m[0][7:].strip() if m else ""
            if not img_url:
                fail += 1
                print(f"FAIL {pid} 카드이미지 URL 없음", flush=True)
                continue

            card = f"{WORK}/{pid}_card.png"
            req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r, open(card, "wb") as f:
                f.write(r.read())
            if os.path.getsize(card) < 30_000:
                fail += 1
                print(f"FAIL {pid} 카드 다운로드 0/미달", flush=True)
                continue

            photo = f"{WORK}/{pid}_new.png"
            out, err = sh([sys.executable, os.path.join(HERE, "gemini_web_compose.py"), card, photo, tab])
            if "LIMIT" in (out + err):
                print("=== 한도 소진 — 중단 (남은 건 내일 재개) ===", flush=True)
                break
            if not os.path.exists(photo) or os.path.getsize(photo) < 50_000:
                fail += 1
                print(f"FAIL {pid} 재합성 실패", flush=True)
                continue
            h = md5(photo)
            if h == prev_md5:  # 직전과 동일 = 밀림 재발 → 1회 재시도
                os.remove(photo)
                out, err = sh([sys.executable, os.path.join(HERE, "gemini_web_compose.py"), card, photo, tab])
                if not os.path.exists(photo) or md5(photo) == prev_md5:
                    fail += 1
                    print(f"FAIL {pid} 중복사진 재발", flush=True)
                    continue
                h = md5(photo)
            prev_md5 = h

            sh(["docker", "cp", photo, f"{CONTAINER}:/tmp/{pid}_new.png"], 120)
            out, _ = sh(["docker", "exec", CONTAINER, PY, "/tmp/rephoto_one.py", pid, f"/tmp/{pid}_new.png"], 300)
            res = [x for x in out.splitlines() if x.startswith("RESULT ")]
            if res and "OK" in res[0]:
                ok += 1
                print(f"OK[{ok}] {pid} 사진 교체", flush=True)
            else:
                fail += 1
                print(f"FAIL {pid} 교체: {(res[0][7:] if res else '?')[:70]}", flush=True)
            for p in (card, photo):
                try:
                    os.remove(p)
                except OSError:
                    pass
        except Exception as e:
            fail += 1
            print(f"ERR {pid} {type(e).__name__}: {str(e)[:80]}", flush=True)
        time.sleep(2)
    print(f"\n=== 완료: 교체 {ok} / 실패 {fail} ===", flush=True)


if __name__ == "__main__":
    main()
