"""번장 소싱 상품의 원문 상세설명에서 하자·상태 문구 스캔 [컨테이너 실행].

배경: 등록 시 번장 원문 description 을 안 읽고 전부 NM 으로 올렸다. 원문에
      "뒷면 하자", "흠집", "찍힘" 등이 있는데 누락하면 컨디션 허위표기 → 클레임 패배
      (2026-07-24 레쿠쟈V 건 발견).

출력: 하자/약사용 표시가 있는 리스팅 목록 → 컨디션·설명 정정 대상.

실행:
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/scan_defects.py
"""

import asyncio
import io
import json
import sys

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.bunjang.co.kr/"}

# 하자/상태 관련 한글 키워드
DEFECT = ["하자", "흠집", "찍힘", "찍힌", "스크래치", "긁힘", "긁힌", "기스", "눌림",
          "휘어", "휨", "구겨", "접힘", "접힌", "손상", "훼손", "변색", "얼룩", "때",
          "화이트", "흰색", "모서리", "각지", "각깨", "각 깨", "데미지", "damage",
          "플레이드", "played", "중고", "사용감", "실금", "미세"]
# 번장 condition 값이 이거면 신품 아님
NOT_NEW = {"LIGHTLY_USED", "USED", "HEAVILY_USED"}


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from sqlalchemy import text as t

    tok = current_tenant_id.set(TENANT)
    try:
        async with get_write_session() as s:
            rows = (await s.execute(t("""
                SELECT id, name_en, site_product_id, market_product_nos
                FROM samba_collected_product
                WHERE tenant_id = :tn AND source_site = 'BUNJANG'
                  AND registered_accounts @> CAST(:kv AS jsonb)
                ORDER BY created_at DESC
            """), {"tn": TENANT, "kv": f'["{KV}"]'})).all()
            print(f"번장 등록분 {len(rows)}건 스캔")

            flagged = []
            async with httpx.AsyncClient(timeout=30, headers=H) as c:
                for pid, en, bpid, nos in rows:
                    if not bpid:
                        continue
                    try:
                        d = (await c.get(
                            f"https://api.bunjang.co.kr/api/pms/v1/products/{bpid}/detail/web"
                        )).json().get("data", {}).get("product", {})
                    except Exception:
                        continue
                    desc = (d.get("description") or "")
                    cond = (d.get("condition") or d.get("productCondition") or "")
                    hits = [k for k in DEFECT if k in desc]
                    if hits or cond in NOT_NEW:
                        flagged.append({
                            "id": pid, "name": en, "bpid": bpid,
                            "listing": (nos or {}).get(KV), "cond": cond,
                            "hits": hits, "desc": desc[:120]})
                        print(f"  ⚠ {(en or '')[:38]:38} | {cond} | {','.join(hits)}")
                        print(f"      {desc[:80]}")
            json.dump(flagged, open("/tmp/defect_flagged.json", "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            print(f"\n하자/약사용 의심 {len(flagged)}건 → /tmp/defect_flagged.json")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
