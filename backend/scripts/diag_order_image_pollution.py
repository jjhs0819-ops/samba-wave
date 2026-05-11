"""주문 이미지/소스 오염 진단 스크립트.

목적:
  1. 특정 주문(20260510H70496)의 현재 DB 상태 + 매칭된 cp 비교
  2. 오염 의심 패턴 전체 카운트 — collected_product_id 가리키는 cp의
     market_product_nos에 (channel_id, product_id) 매핑이 실제로 없는 주문

수정 X. 조회만.
"""

import asyncio

import asyncpg

from backend.core.config import settings


TARGET_ORDER_NUMBER = "20260510H70496"


async def main():
    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        print("=" * 80)
        print(f"[1] 타겟 주문: {TARGET_ORDER_NUMBER}")
        print("=" * 80)
        rows = await conn.fetch(
            """
            SELECT id, order_number, channel_id, channel_name, product_id,
                   product_name, product_image, source_site, source_url,
                   collected_product_id
            FROM samba_order
            WHERE order_number = $1
            ORDER BY created_at DESC
            LIMIT 5
            """,
            TARGET_ORDER_NUMBER,
        )
        for r in rows:
            print(f"  order_id            : {r['id']}")
            print(f"  channel_id          : {r['channel_id']}")
            print(f"  channel_name        : {r['channel_name']}")
            print(f"  product_id          : {r['product_id']}")
            print(f"  product_name        : {r['product_name']}")
            print(f"  source_site         : {r['source_site']}")
            print(f"  source_url          : {r['source_url']}")
            print(f"  product_image       : {r['product_image']}")
            print(f"  collected_product_id: {r['collected_product_id']}")
            print("-" * 80)
            cpid = r["collected_product_id"]
            if cpid:
                cp = await conn.fetchrow(
                    """
                    SELECT id, name, source_site, site_product_id, source_url,
                           images, market_product_nos
                    FROM samba_collected_product
                    WHERE id = $1
                    """,
                    cpid,
                )
                if cp:
                    print(f"  → 매칭된 cp.id           : {cp['id']}")
                    print(f"  → cp.name                : {cp['name']}")
                    print(f"  → cp.source_site         : {cp['source_site']}")
                    print(f"  → cp.site_product_id     : {cp['site_product_id']}")
                    print(f"  → cp.source_url          : {cp['source_url']}")
                    imgs = cp["images"]
                    print(f"  → cp.images[0]           : {imgs[0] if imgs else None}")
                    print(f"  → cp.market_product_nos  : {cp['market_product_nos']}")
                else:
                    print(f"  → cp.id={cpid} 존재 안 함")
            print("=" * 80)

        print()
        print("=" * 80)
        print("[2] 동일 product_id로 등록된 cp 후보 (글로벌 충돌 여부 체크)")
        print("=" * 80)
        if rows:
            r = rows[0]
            pid = r["product_id"]
            ch_id = r["channel_id"]
            print(f"  검색 product_id={pid!r}  channel_id={ch_id!r}")
            cands = await conn.fetch(
                """
                SELECT id, name, source_site, market_product_nos
                FROM samba_collected_product
                WHERE market_product_nos::text LIKE $1
                LIMIT 20
                """,
                f"%{pid}%",
            )
            for c in cands:
                mpn = c["market_product_nos"] or {}
                # 어느 키에 이 product_id가 들어있는지
                hits = []
                if isinstance(mpn, dict):
                    for k, v in mpn.items():
                        sv = str(v) if not isinstance(v, dict) else str(v)
                        if pid and pid in sv:
                            hits.append(k)
                print(
                    f"  cp={c['id']} site={c['source_site']:<10} "
                    f"name={(c['name'] or '')[:40]:<40} "
                    f"matched_keys={hits}"
                )

        print()
        print("=" * 80)
        print(
            "[3a] _unreg_cache 자가증식 의심 — 동일 (product_id, channel_name) 그룹에서"
        )
        print("     같은 source_url을 공유하는 주문 수 (>=2건이면 캐시 전파 흔적)")
        print("=" * 80)
        clusters = await conn.fetch(
            """
            SELECT product_id, channel_name, source_url, COUNT(*) AS cnt,
                   MIN(created_at) AS first_at, MAX(created_at) AS last_at
            FROM samba_order
            WHERE source_url IS NOT NULL
              AND product_id IS NOT NULL
              AND channel_name IS NOT NULL
              AND collected_product_id IS NULL
            GROUP BY product_id, channel_name, source_url
            HAVING COUNT(*) >= 2
            ORDER BY COUNT(*) DESC
            LIMIT 30
            """
        )
        print("  collected_product_id NULL인데 같은 source_url 공유 클러스터 상위 30:")
        for c in clusters:
            print(
                f"    cnt={c['cnt']:<4} ch={c['channel_name'][:25]:<25} "
                f"pid={c['product_id'][:15]:<15} url={(c['source_url'] or '')[:60]}"
            )

        print()
        print("=" * 80)
        print(
            "[3b] 본 사례 동일군 — channel_name='롯데홈쇼핑(037800LT)' + source_url에 musinsa"
        )
        print("=" * 80)
        same = await conn.fetch(
            """
            SELECT id, order_number, product_id, product_name, source_url, product_image
            FROM samba_order
            WHERE channel_name = '롯데홈쇼핑(037800LT)'
              AND source_url LIKE '%musinsa.com%'
            ORDER BY created_at DESC
            LIMIT 50
            """
        )
        print(f"  매칭: {len(same)}건")
        for s in same[:20]:
            print(
                f"    {s['order_number']} pid={s['product_id']:<12} "
                f"name={(s['product_name'] or '')[:40]:<40} url={(s['source_url'] or '')[:50]}"
            )

        print()
        print("=" * 80)
        print(
            "[4] 오염 의심 카운트(원래 [3]) — collected_product_id 정합성 (1000건 샘플)"
        )
        print("=" * 80)
        sample = await conn.fetch(
            """
            SELECT o.id, o.order_number, o.channel_id, o.product_id,
                   o.source_site, o.collected_product_id,
                   cp.market_product_nos, cp.source_site AS cp_site, cp.name AS cp_name
            FROM samba_order o
            JOIN samba_collected_product cp ON cp.id = o.collected_product_id
            WHERE o.collected_product_id IS NOT NULL
              AND o.product_id IS NOT NULL
              AND o.created_at > NOW() - INTERVAL '30 days'
            ORDER BY o.created_at DESC
            LIMIT 1000
            """
        )
        polluted = []
        for s in sample:
            mpn = s["market_product_nos"] or {}
            ch = str(s["channel_id"] or "")
            pid = str(s["product_id"] or "")
            if not isinstance(mpn, dict):
                continue
            # (channel_id, product_id) 정확매칭 확인
            v = mpn.get(ch)
            ok = False
            if v:
                if isinstance(v, dict):
                    for sub in (
                        v.get("smartstoreChannelProductNo"),
                        v.get("originProductNo"),
                        v.get("channelProductNo"),
                    ):
                        if sub and str(sub) == pid:
                            ok = True
                            break
                elif str(v) == pid:
                    ok = True
            if not ok:
                # master_code 매칭(playauto)도 통과로 간주 — 글로벌 키에 pid가 값으로 있으면
                # 별도 검사 어려우니 일단 보수적으로 의심 목록에 넣음
                polluted.append(s)
        print(f"  샘플 1000건 중 오염 의심: {len(polluted)}건")
        for p in polluted[:10]:
            print(
                f"    order={p['order_number']} ch={p['channel_id']} "
                f"pid={p['product_id']} src={p['source_site']} "
                f"cp_site={p['cp_site']} cp_name={(p['cp_name'] or '')[:40]}"
            )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
