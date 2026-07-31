"""라이브 리스팅 상세설명 재전송 [컨테이너 실행].

템플릿(배너/HTML)을 바꿔도 이미 올라간 리스팅에는 반영되지 않는다.
2026-07-23 관세 문구 정정처럼 안내가 바뀌면 전 리스팅에 다시 밀어넣어야 한다.

가격/재고는 건드리지 않는다 — dispatch_to_market 이 기존 Offer 를 수정만 한다.
(ebay.py 수정으로 5xx 시 신규등록 폴백은 차단돼 있으니 리스팅이 내려갈 위험 없음)

실행:
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/refresh_descriptions.py [--limit N]
"""

import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"  # k-tcg_vault 전용


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.account.resolver import resolve_market_creds
    from backend.domain.samba.proxy.ebay import EbayClient
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from sqlalchemy import text as t
    from sqlmodel import select

    limit = (
        int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 999
    )
    tok = current_tenant_id.set(TENANT)
    ok = fail = 0
    try:
        async with get_write_session() as s:
            acc = (
                (
                    await s.execute(
                        select(SambaMarketAccount).where(SambaMarketAccount.id == KV)
                    )
                )
                .scalars()
                .first()
            )
            _ax = getattr(acc, "additional_fields", None) or {}
            _cr = (
                await resolve_market_creds(
                    s, TENANT, market_type="ebay", store_key="store_ebay"
                )
                or {}
            )
            ecli = EbayClient(
                _cr.get("clientId")
                or _cr.get("appId")
                or _ax.get("clientId")
                or _ax.get("appId", ""),
                _cr.get("devId") or _ax.get("devId", ""),
                _cr.get("clientSecret")
                or _cr.get("certId")
                or _ax.get("clientSecret")
                or _ax.get("certId", ""),
                _cr.get("oauthToken")
                or _cr.get("authToken")
                or _ax.get("oauthToken")
                or _ax.get("authToken", ""),
            )

            rows = (
                await s.execute(
                    t("""
                SELECT id FROM samba_collected_product
                WHERE tenant_id = :tn AND registered_accounts @> CAST(:kv AS jsonb)
                ORDER BY created_at
            """),
                    {"tn": TENANT, "kv": f'["{KV}"]'},
                )
            ).all()
            print(f"대상 {len(rows)}건")
            for i, (pid,) in enumerate(rows[:limit], 1):
                p = (
                    (
                        await s.execute(
                            select(SambaCollectedProduct).where(
                                SambaCollectedProduct.id == pid
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                no = (p.market_product_nos or {}).get(KV, "")
                if not no:
                    continue
                # [중요] 카테고리를 정책으로 추정해 넣으면 안 된다. 기존 리스팅의 컨디션
                # (Graded 등)과 안 맞아 25021 CONDITION_ID 오류로 전부 실패한다.
                # 반드시 현재 offer 의 categoryId 를 그대로 재사용한다(2026-07-23 15건 실패).
                cat = ""
                try:
                    _o = await ecli._call(
                        "GET", "/sell/inventory/v1/offer", params={"sku": p.id}
                    )
                    for _off in _o.get("offers", []):
                        cat = _off.get("categoryId") or ""
                        if cat:
                            break
                except Exception:
                    pass
                if not cat:
                    cat = (
                        "108857"
                        if p.applied_policy_id
                        in ("pol_kpopcard_v1", "pol_kpopgoods_v1")
                        else "183454"
                    )
                try:
                    res = await dispatch_to_market(
                        s,
                        "ebay",
                        p.model_dump(),
                        category_id=cat,
                        account=acc,
                        existing_product_no=no,
                    )
                    if res.get("success"):
                        ok += 1
                        print(f"{i:>3}. OK {(p.name_en or p.name)[:44]}")
                    else:
                        fail += 1
                        print(
                            f"{i:>3}. 실패 {(p.name_en or p.name)[:36]} — {str(res.get('message'))[:70]}"
                        )
                except Exception as e:
                    fail += 1
                    print(f"{i:>3}. 예외 {(p.name_en or p.name)[:36]} — {str(e)[:70]}")
            print(f"완료: 성공 {ok} / 실패 {fail}")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
