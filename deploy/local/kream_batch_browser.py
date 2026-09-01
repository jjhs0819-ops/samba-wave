# -*- coding: utf-8 -*-
"""크림 카드 → eBay 대량등록 [호스트 실행] — 합성사진은 브라우저 제미나이(과금 0원).

왜 호스트인가: 사진 합성이 웨일 CDP + 윈도우 클립보드를 쓰므로 컨테이너에서 못 돈다.
크림 조회/등록만 컨테이너 스크립트에 위임한다.

건당 흐름:
  컨테이너 kream_probe_one.py (실시간 재고·원가·게이트)
  → 호스트에서 카드 이미지 다운로드
  → gemini_web_compose.py 로 포스트잇 합성 (브라우저)
  → docker cp 로 사진 투입
  → 컨테이너 kream_register_one.py 로 eBay 등록

사용:
  python3 kream_batch_browser.py <목표건수> <탭ID> [--start N]
"""

import io
import json
import os
import subprocess
import sys
import time
import urllib.request

# [중요] 윈도우 기본 stdout 이 cp949 라 'Pokémon' 의 é 에서 UnicodeEncodeError 가 난다.
# 등록 자체는 이미 끝난 뒤 로그 출력에서 터져 성공 건이 ERR 로 잘못 기록된다.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "..", "samba-tools", "ebay_sourcing")
CONTAINER = "local-samba-api-1"
PY = "/app/backend/.venv/bin/python3"
WORK = "C:/tmp/batch_browser"


def sh(args, timeout=900):
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    r = subprocess.run(args, capture_output=True, timeout=timeout, env=env)
    return (r.stdout or b"").decode("utf-8", "replace"), (r.stderr or b"").decode("utf-8", "replace")


def dexec(script, *args, timeout=900):
    out, _ = sh(["docker", "exec", CONTAINER, PY, f"/tmp/{script}", *[str(a) for a in args]], timeout)
    for line in out.splitlines():
        if line.startswith("RESULT "):
            return line[len("RESULT ") :].strip()
    return ""


def push(local, remote):
    """컨테이너로 파일 투입. 실패하면 즉시 예외 — 조용히 넘어가면 안 된다.

    [2026-08-29] cp 실패를 무시한 채 진행해 컨테이너에 스크립트가 없는 상태로
    348건을 헛돌았다. 판정이 전부 빈값이 되어 '건너뜀'으로만 찍혔다.
    """
    out, err = sh(["docker", "cp", local, f"{CONTAINER}:{remote}"], 120)
    verify = subprocess.run(
        ["docker", "exec", CONTAINER, "test", "-s", remote],
        capture_output=True, env=dict(os.environ, MSYS_NO_PATHCONV="1"),
    )
    if verify.returncode != 0:
        raise RuntimeError(f"컨테이너 투입 실패: {remote} | {(out + err).strip()[:150]}")


def main():
    limit = int(sys.argv[1])
    tab = sys.argv[2]
    start = int(sys.argv[sys.argv.index("--start") + 1]) if "--start" in sys.argv else 0
    # [2026-08-29] 사진 검수 분리 모드. 제미나이가 엉뚱한 카드를 그려도 첨부 개수
    # 검증으로는 못 막는다(갸라도스 사고). --photo-only 로 사진만 만들어 두고,
    # 사람이 눈으로 대조한 뒤 별도 등록 단계로 넘긴다.
    photo_only = "--photo-only" in sys.argv
    manifest = []

    os.makedirs(WORK, exist_ok=True)

    # 컨테이너 스크립트 최신화
    for f in ("kream_probe_one.py", "kream_register_one.py"):
        push(os.path.join(TOOLS, f), f"/tmp/{f}")

    # 후보 목록을 컨테이너에서 호스트로 꺼내기
    # [2026-08-29] 이미 등록된 건은 목록 단계에서 걸러진 pick_new.json 을 쓴다.
    # 예전엔 전체 목록을 돌며 건당 '이미 등록됨' 으로 튕겨 시간만 버렸다.
    sh(["docker", "cp", f"{CONTAINER}:/tmp/pick_new.json", f"{WORK}/pick.json"], 120)
    cands = json.load(open(f"{WORK}/pick.json", encoding="utf-8"))[start:]
    print(f"후보 {len(cands)}건 | 목표 {limit}건", flush=True)

    ok = skip = fail = 0
    for c in cands:
        if ok >= limit:
            break
        pid = c["product_id"]
        sku = c.get("sku") or ""
        try:
            raw = dexec("kream_probe_one.py", pid, timeout=180)
            if not raw:
                # RESULT 줄 자체가 없다 = 스크립트/환경 문제. 후보를 계속 넘겨봐야 소용없다.
                print(f"ABORT {pid} 판정 결과 없음 — 컨테이너 스크립트/환경 확인 필요", flush=True)
                break
            info = json.loads(raw)
            if not info.get("ok"):
                skip += 1
                print(f"SKIP {pid} {info.get('reason')}", flush=True)
                continue
            # 품번은 프로브가 크림에서 실시간으로 가져온 값을 우선 사용
            sku = info.get("sku") or sku or f"KR{pid}"

            card = f"{WORK}/{pid}_card.png"
            # 크림 CDN 은 기본 UA 를 막으므로 브라우저 UA 로 요청
            req = urllib.request.Request(info["img_url"], headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r, open(card, "wb") as f:
                f.write(r.read())

            photo = f"{WORK}/{pid}_postit.png"
            out, err = sh(
                [sys.executable, os.path.join(HERE, "gemini_web_compose.py"), card, photo, tab],
                timeout=1200,
            )
            if not os.path.exists(photo) or os.path.getsize(photo) < 50_000:
                fail += 1
                print(f"FAIL {pid} 사진생성: {(out + err).strip().splitlines()[-1][:70] if (out + err).strip() else ''}", flush=True)
                continue

            if photo_only:
                ok += 1
                manifest.append({
                    "product_id": pid, "sku": sku, "cost": int(info["cost"]),
                    "name_en": info["name_en"], "name_ko": info["name_ko"],
                    "photo": photo, "card": card, "img_url": info["img_url"],
                })
                print(f"PHOTO[{ok}] {pid} | {sku:18s} | {info['name_en'][:45]}", flush=True)
                continue

            push(photo, f"/tmp/{pid}_postit.png")
            res = dexec(
                "kream_register_one.py",
                pid,
                sku,
                int(info["cost"]),
                f"/tmp/{pid}_postit.png",
                info["name_en"],
                info["name_ko"],
                timeout=300,
            )
            if res.startswith("OK"):
                ok += 1
                print(
                    f"OK[{ok}] {pid} | {sku:18s} | 원가{info['cost']:>8,.0f} | {res.split()[1]} | {info['name_en'][:38]}",
                    flush=True,
                )
            else:
                fail += 1
                print(f"FAIL {pid} 등록: {res[:80]}", flush=True)

            for p in (card, photo):
                try:
                    os.remove(p)
                except OSError:
                    pass
        except Exception as e:
            fail += 1
            print(f"ERR {pid} {type(e).__name__}: {str(e)[:90]}", flush=True)
        time.sleep(2)

    if photo_only:
        mf = os.path.join(WORK, "manifest.json")
        with open(mf, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)
        print(f"\n사진 {len(manifest)}건 생성 — 검수 목록: {mf}", flush=True)
    print(f"\n=== 완료: 성공 {ok} / 건너뜀 {skip} / 실패 {fail} ===", flush=True)


if __name__ == "__main__":
    main()
