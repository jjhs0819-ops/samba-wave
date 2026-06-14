# -*- coding: utf-8 -*-
"""#418 검증 — 전면 자유입력 + 조합 추가금 빌드 payload 확인 (build_only, PUT 없음).

실제 ESM 그룹 해석(cat 300027334)으로 register_esm_options(build_only=True) 호출해
빌드된 payload 가 (a)전부 recommendedOptValueNo=0+koreanText (b)비표준 값도 미발행 없이
포함 (c)조합 addAmnt=절대가격 차액 인지 검사.

실행(컨테이너): /app/backend/.venv/bin/python3 /tmp/vfb.py
"""

import asyncio
import traceback

from sqlmodel import select

from backend.db.orm import get_read_session
from backend.domain.samba.account.model import SambaMarketAccount
from backend.domain.samba.proxy.esmplus import ESMPlusClient, resolve_esm_credentials
from backend.domain.samba.proxy.esmplus import register_esm_options
from backend.domain.samba.plugins.markets.gmarket import _to_grouped_options

CAT = "300027334"


async def main() -> None:
    async with get_read_session() as session:
        accts = (
            await session.exec(
                select(SambaMarketAccount).where(
                    SambaMarketAccount.market_type == "gmarket",
                    SambaMarketAccount.is_active == True,  # noqa: E712
                )
            )
        ).all()
        client = None
        for a in accts:
            h, s = await resolve_esm_credentials(session, a)
            seller = (a.seller_id or "").strip()
            if not seller:
                ex = getattr(a, "additional_fields", None) or {}
                seller = (ex.get("apiKey") or ex.get("sellerId") or "").strip()
            if h and s and seller:
                client = ESMPlusClient(h, s, seller, site="gmarket")
                print(f"계정: {a.account_label}", flush=True)
                break
        if not client:
            print("계정 없음", flush=True)
            return

        try:
            # CASE 1 — 1축, 비표준 옵션값 포함(괄호코드·영문약어)
            opts1 = [
                {"name": "블랙", "stock": 5, "isSoldOut": False},
                {"name": "카키(054)", "stock": 0, "isSoldOut": True},
                {"name": "C10(165mm)", "stock": 9, "isSoldOut": False},
                {"name": "WHT", "stock": 3, "isSoldOut": False},
            ]
            g1 = _to_grouped_options(opts1, [])
            r1 = await register_esm_options(
                client, "0", CAT, g1, site="gmarket", build_only=True
            )
            print("\n=== CASE1 1축 자유입력 ===", flush=True)
            print(
                f"success={r1.get('success')} matched={r1.get('matched')} "
                f"requested={r1.get('requested')} type={r1.get('type')}",
                flush=True,
            )
            dets = ((r1.get("payload") or {}).get("independent") or {}).get(
                "details"
            ) or []
            for d in dets:
                print(
                    f"  valueNo={d.get('recommendedOptValueNo')} "
                    f"kt={(d.get('recommendedOptValue') or {}).get('koreanText')!r} "
                    f"qty={d.get('qty')} sold={d.get('isSoldOut')} add={d.get('addAmnt')}",
                    flush=True,
                )
            allzero = all(d.get("recommendedOptValueNo") == 0 for d in dets)
            print(
                f"  >>> 전부 valueNo=0: {allzero} / 발행 {len(dets)}/{len(opts1)}",
                flush=True,
            )

            # CASE 2 — 2축 조합 + per-combo 가격(추가금 차액 검증)
            opts2 = [
                {"name": "블랙/S", "stock": 5, "isSoldOut": False, "price": 10000},
                {"name": "블랙/L", "stock": 3, "isSoldOut": False, "price": 13300},
                {"name": "위트/S", "stock": 0, "isSoldOut": True, "price": 10000},
                {"name": "위트/L", "stock": 7, "isSoldOut": False, "price": 16600},
            ]
            g2 = _to_grouped_options(opts2, [])
            print("\n=== CASE2 2축 조합+추가금 ===", flush=True)
            print(
                f"  _to_grouped 축: {[(x.get('name'), [v.get('name') for v in x.get('values', [])]) for x in g2]}",
                flush=True,
            )
            r2 = await register_esm_options(
                client, "0", CAT, g2, site="gmarket", build_only=True
            )
            print(
                f"  success={r2.get('success')} matched={r2.get('matched')} type={r2.get('type')}",
                flush=True,
            )
            cdets = ((r2.get("payload") or {}).get("combination") or {}).get(
                "details"
            ) or []
            for d in cdets:
                k1 = (d.get("recommendedOptValue1") or {}).get("koreanText")
                k2 = (d.get("recommendedOptValue2") or {}).get("koreanText")
                print(
                    f"  [{k1}/{k2}] no1={d.get('recommendedOptValueNo1')} "
                    f"no2={d.get('recommendedOptValueNo2')} qty={d.get('qty')} "
                    f"sold={d.get('isSoldOut')} add={d.get('addAmnt')}",
                    flush=True,
                )
            allzero2 = all(
                d.get("recommendedOptValueNo1") == 0
                and d.get("recommendedOptValueNo2") == 0
                for d in cdets
            )
            print(
                f"  >>> 전부 valueNo=0: {allzero2} (기대 add: 블랙/S=0, 블랙/L=3300, 위트/L=6600)",
                flush=True,
            )
        finally:
            await client.aclose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        traceback.print_exc()
