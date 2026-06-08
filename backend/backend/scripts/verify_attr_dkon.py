"""11번가 선글라스 get_category_attributes ①/② 판별 + 롯데ON dk-on 미러 후 길이 (읽기 전용)."""

import asyncio
import json
from sqlalchemy import text
from backend.db.orm import get_write_session
from backend.domain.samba.proxy.elevenst import ElevenstClient
from backend.domain.samba.image.service import ImageTransformService


async def main() -> None:
    async with get_write_session() as session:
        # ── 11번가 선글라스 ──
        print("[11번가 선글라스 get_category_attributes]")
        srow = (
            await session.execute(
                text("""
            SELECT s.mapped_categories, s.target_account_ids
            FROM samba_shipment s JOIN samba_collected_product cp ON cp.id=s.product_id
            WHERE s.status='failed' AND s.created_at >= now() - interval '3 days'
              AND cp.category3='선글라스'
              AND EXISTS (SELECT 1 FROM samba_market_account ma WHERE ma.market_type='11st'
                          AND CAST(s.target_account_ids AS text) LIKE '%'||ma.id||'%')
            LIMIT 1
        """)
            )
        ).fetchone()
        if not srow:
            print("  선글라스 11st 실패 shipment 없음")
        else:
            mc = srow.mapped_categories
            if isinstance(mc, str):
                try:
                    mc = json.loads(mc)
                except Exception:
                    mc = {}
            cat11 = (mc or {}).get("11st", "")
            print(f"  11st 매핑 카테고리: {cat11!r}")
            # 11st 계정 api_key
            acc = (
                await session.execute(
                    text("""
                SELECT id, api_key, additional_fields FROM samba_market_account
                WHERE market_type='11st' AND COALESCE(api_key,'')<>'' LIMIT 1
            """)
                )
            ).fetchone()
            api_key = ""
            if acc:
                api_key = acc.api_key or ""
            if not api_key:
                acc2 = (
                    await session.execute(
                        text("""
                    SELECT additional_fields FROM samba_market_account
                    WHERE market_type='11st' LIMIT 5
                """)
                    )
                ).fetchall()
                for a in acc2:
                    af = a.additional_fields or {}
                    if isinstance(af, dict) and af.get("apiKey"):
                        api_key = af["apiKey"]
                        break
            print(f"  api_key 확보: {bool(api_key)}")
            if api_key and cat11:
                cli = ElevenstClient(api_key)
                attrs = await cli.get_category_attributes(str(cat11))
                print(f"  get_category_attributes 결과 {len(attrs)}개")
                for a in attrs:
                    print(f"    {a}")
                has_chisu = any("치수" in str(a.get("nm", "")) for a in attrs)
                print(
                    f"  >>> 치수 attr 포함: {has_chisu}  → {'② 값거부 의심' if has_chisu else '① 조회빈값=XML누락'}"
                )

        # ── 롯데ON dk-on 미러 후 길이 ──
        print("\n[롯데ON dk-on 미러 후 길이]")
        svc = ImageTransformService(session)
        u = "https://img.dk-on.com/contents/editor_images/20251203/test.jpg"
        # 실제 실패 상품의 긴 dk-on URL 가져오기
        lrow = (
            await session.execute(
                text("""
            SELECT cp.images FROM samba_shipment s JOIN samba_collected_product cp ON cp.id=s.product_id
            WHERE s.status='failed' AND s.created_at >= now() - interval '3 days'
              AND CAST(s.transmit_error AS text) LIKE '%origImgFileNm%'
              AND CAST(cp.images AS text) LIKE '%dk-on%' LIMIT 1
        """)
            )
        ).fetchone()
        if lrow:
            imgs = lrow.images
            if isinstance(imgs, str):
                try:
                    imgs = json.loads(imgs)
                except Exception:
                    imgs = []
            longu = max(
                (str(x) for x in (imgs or []) if "dk-on" in str(x)), key=len, default=u
            )
            print(f"  원본 len={len(longu)} : {longu[:90]}")
            try:
                b = await svc._download_image(longu)
                print(f"  다운로드 OK {len(b):,} bytes")
                mirrored, _ = await svc.mirror_external_to_r2([longu])
                # dk-on은 차단목록에 없어 원본유지될 것 — 길이만 비교
                print(
                    f"  현재 미러결과: {mirrored[0][:90] if mirrored else '없음'} (len={len(mirrored[0]) if mirrored else 0})"
                )
            except Exception as e:
                print(f"  다운로드 FAIL {type(e).__name__}: {str(e)[:60]}")


if __name__ == "__main__":
    asyncio.run(main())
