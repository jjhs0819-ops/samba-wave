"""크림 상품 1건 실시간 조회 + 낱장카드 게이트 [컨테이너 실행].

호스트 배치가 건별로 호출한다. 결과를 JSON 한 줄로 출력.
  통과: {"ok":true,"name_en":..,"name_ko":..,"cost":..,"img_url":..}
  탈락: {"ok":false,"reason":".."}
"""

import asyncio
import io
import json
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
GRADE_RE = re.compile(r"ungraded|psa|brg|bgs|cgc", re.I)
BAD_TITLE_RE = re.compile(
    r"booster|\bbox\b|\bpack\b|elite\s*trainer|\betb\b|\bkit\b|\bset\b|spinner|"
    r"\btin\b|\bbundle\b|\bcase\b|deck|starter|미개봉|부스터|박스|팩(?!\w)|세트|덱",
    re.I,
)


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.proxy.kream import KreamPartnerClient
    from sqlmodel import select

    pid = sys.argv[1]
    tok = current_tenant_id.set(TENANT)
    out = {"ok": False, "reason": "unknown"}
    try:
        from sqlalchemy import text as t

        async with get_write_session() as s:
            # [중요] 이미 등록된 건은 여기서 잘라낸다.
            # 후보 목록(pick.json)은 스냅샷이라, 목록 생성 후 다른 배치가 등록한 건이
            # 그대로 남아 있다. 이 가드가 없으면 등록된 상품에 사진 합성까지 다시 돌려
            # 몇 시간을 허비한다(2026-08-17 실측: 63건 헛돌음).
            dup = (
                await s.execute(
                    t(
                        "SELECT 1 FROM samba_collected_product WHERE source_site='KREAM' "
                        "AND site_product_id=:p AND registered_accounts::text LIKE :a LIMIT 1"
                    ),
                    {"p": pid, "a": f"%{KV}%"},
                )
            ).first()
            if dup:
                print('RESULT {"ok": false, "reason": "이미 등록됨"}')
                return
            kacc = (
                (await s.execute(select(SambaMarketAccount).where(SambaMarketAccount.market_type == "kream")))
                .scalars()
                .first()
            )
            ext = kacc.additional_fields if isinstance(kacc.additional_fields, dict) else {}
            k = KreamPartnerClient(
                str(ext.get("apiService") or ""),
                str(ext.get("apiKey") or kacc.api_key or ""),
                str(ext.get("apiSecret") or kacc.api_secret or ""),
            )
        code, body = await k.get_product(int(pid))
        if code != 200:
            out = {"ok": False, "reason": f"조회실패 {code}"}
        else:
            name_en = body.get("name") or ""
            name_ko = body.get("translated_name") or name_en
            if BAD_TITLE_RE.search(f"{name_en} {name_ko}"):
                out = {"ok": False, "reason": "밀봉/굿즈제목"}
            else:
                opts = body.get("options") or []
                if not any(GRADE_RE.search(str(o.get("name_display") or "")) for o in opts):
                    out = {"ok": False, "reason": "등급옵션없음(카드아님)"}
                else:
                    ask, fast = None, False
                    for o in opts:
                        if not GRADE_RE.search(str(o.get("name_display") or "")):
                            continue
                        n, h = o.get("lowest_normal_price"), o.get("lowest_100_price")
                        if n:
                            ask, fast = n, False
                            break
                        if h and ask is None:
                            ask, fast = h, True
                    img = (body.get("main_images") or [None])[0]
                    if not ask:
                        out = {"ok": False, "reason": "재고없음"}
                    elif not img:
                        out = {"ok": False, "reason": "이미지없음"}
                    else:
                        cost = float(ask) + (int(ask * 0.033) // 10) * 10 + (5000 if fast else 3000)
                        if cost > 200000:
                            out = {"ok": False, "reason": f"원가초과 {cost:,.0f}"}
                        else:
                            mn = body.get("model_number")
                            sku = mn if mn not in ("-", "", None) else f"KR{pid}"
                            out = {
                                "ok": True,
                                "name_en": name_en,
                                "name_ko": name_ko,
                                "cost": cost,
                                "img_url": img,
                                "sku": sku,
                            }
    except Exception as e:
        out = {"ok": False, "reason": f"{type(e).__name__}: {str(e)[:80]}"}
    finally:
        current_tenant_id.reset(tok)
    print("RESULT " + json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
