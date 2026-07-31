"""밀봉 부스터팩·박스를 183455 카테고리로 재등록 [컨테이너 실행].

왜:
  팩/박스가 183454(싱글카드)에 올라가 있으면 eBay 가 우리 컨디션 조합
  (USED_VERY_GOOD + Card Condition 40001)을 거부한다(25021). 그래서 상세설명·가격
  수정이 전부 실패한다. 밀봉 상품의 올바른 카테고리는 183455(Lot/팩)이고 거기선
  condition=NEW 로 등록된다. (2026-07-23, 이전 6건과 동일한 처리)

주의:
  eBay 는 라이브 리스팅의 카테고리 변경을 허용하지 않는다 → 종료 후 재등록이며
  건당 등록수수료가 발생한다. 되돌릴 수 없으므로 --dry 로 목록 먼저 확인할 것.

실행:
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 \
      /tmp/recategorize_packs.py [--dry] [--limit N]
"""

import asyncio
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"  # k-tcg_vault 전용
NEW_CAT = "183455"  # CCG Mixed Card Lots — 밀봉 팩/박스
# 제목에 이게 있으면 밀봉 상품으로 본다. 싱글카드를 잘못 옮기면 안 되므로 보수적으로.
SEALED = re.compile(r"(booster\s+(pack|box)|booster\b|\bbox\b|high\s+class)", re.I)


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.account.resolver import resolve_market_creds
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.proxy.ebay import EbayClient
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from sqlalchemy import text as t
    from sqlmodel import select

    dry = "--dry" in sys.argv
    limit = (
        int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 999
    )
    tok = current_tenant_id.set(TENANT)
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
            ax = getattr(acc, "additional_fields", None) or {}
            cr = (
                await resolve_market_creds(
                    s, TENANT, market_type="ebay", store_key="store_ebay"
                )
                or {}
            )
            ec = EbayClient(
                cr.get("clientId")
                or cr.get("appId")
                or ax.get("clientId")
                or ax.get("appId", ""),
                cr.get("devId") or ax.get("devId", ""),
                cr.get("clientSecret")
                or cr.get("certId")
                or ax.get("clientSecret")
                or ax.get("certId", ""),
                cr.get("oauthToken")
                or cr.get("authToken")
                or ax.get("oauthToken")
                or ax.get("authToken", ""),
            )

            rows = (
                await s.execute(
                    t("""
                SELECT id, name_en, name FROM samba_collected_product
                WHERE tenant_id = :tn AND registered_accounts @> CAST(:kv AS jsonb)
                ORDER BY created_at
            """),
                    {"tn": TENANT, "kv": f'["{KV}"]'},
                )
            ).all()

            targets = []
            for pid, en, ko in rows:
                title = en or ko or ""
                if not SEALED.search(title):
                    continue
                try:
                    o = await ec._call(
                        "GET", "/sell/inventory/v1/offer", params={"sku": pid}
                    )
                except Exception:
                    continue
                offers = o.get("offers", [])
                cat = next(
                    (x.get("categoryId") for x in offers if x.get("categoryId")), ""
                )
                if cat and cat != NEW_CAT:
                    targets.append((pid, title, cat, offers))

            print(f"재등록 대상 {len(targets)}건 (현재 카테고리 ≠ {NEW_CAT})")
            ok = fail = 0
            for i, (pid, title, cat, offers) in enumerate(targets[:limit], 1):
                print(
                    f"{i:>2}. {'DRY' if dry else 'RUN'} {title[:44]} | {cat} → {NEW_CAT}"
                )
                if dry:
                    continue
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
                try:
                    # 기존 리스팅 종료 + Offer/Item 삭제 (카테고리 변경은 재등록만 가능)
                    for o in offers:
                        oid = o.get("offerId")
                        if o.get("status") == "PUBLISHED":
                            try:
                                await ec.withdraw_offer(oid)
                            except Exception as e:
                                print(f"    withdraw 실패(계속): {str(e)[:60]}")
                        try:
                            await ec._call("DELETE", f"/sell/inventory/v1/offer/{oid}")
                        except Exception:
                            pass
                    try:
                        await ec._call(
                            "DELETE", f"/sell/inventory/v1/inventory_item/{pid}"
                        )
                    except Exception:
                        pass

                    res = await dispatch_to_market(
                        s,
                        "ebay",
                        p.model_dump(),
                        category_id=NEW_CAT,
                        account=acc,
                        existing_product_no="",
                    )
                    if res.get("success"):
                        lid = res.get("data", {}).get("listingId") or res.get(
                            "product_no"
                        )
                        d = dict(p.market_product_nos or {})
                        d[KV] = lid
                        p.market_product_nos = d
                        s.add(p)
                        await s.commit()
                        ok += 1
                        print(f"    재등록 완료 → {lid}")
                    else:
                        fail += 1
                        print(f"    재등록 실패: {str(res.get('message'))[:90]}")
                except Exception as e:
                    fail += 1
                    print(f"    예외: {str(e)[:90]}")
            print(f"\n완료: 성공 {ok} / 실패 {fail} / 대상 {len(targets)}")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
