"""롯데ON origImgFileNm byte초과 + 11번가 키속성 누락 실데이터 (읽기 전용)."""

import asyncio
import json
import re
from collections import Counter
from sqlalchemy import text
from backend.db.orm import get_write_session


async def main() -> None:
    async with get_write_session() as session:
        # ── 롯데ON byte초과 ──
        print("=" * 60)
        print("[롯데ON origImgFileNm byte초과]")
        rows = (
            await session.execute(
                text("""
            SELECT s.transmit_error, cp.images
            FROM samba_shipment s JOIN samba_collected_product cp ON cp.id=s.product_id
            WHERE s.status='failed' AND s.created_at >= now() - interval '3 days'
              AND CAST(s.transmit_error AS text) LIKE '%origImgFileNm%'
            LIMIT 100
        """)
            )
        ).fetchall()
        limit_msgs = Counter()
        url_lens = []
        hosts = Counter()
        for r in rows:
            te = r.transmit_error
            if isinstance(te, str):
                try:
                    te = json.loads(te)
                except Exception:
                    te = {"_": te}
            msg = (
                " ".join(str(v) for v in te.values())
                if isinstance(te, dict)
                else str(te)
            )
            m = re.search(r"(\d+)\s*Byte", msg)
            if m:
                limit_msgs[m.group(1)] += 1
            imgs = r.images
            if isinstance(imgs, str):
                try:
                    imgs = json.loads(imgs)
                except Exception:
                    imgs = []
            for u in imgs or []:
                url_lens.append(len(str(u)))
                hosts[re.sub(r"^https?://", "", str(u)).split("/")[0].lower()] += 1
        print(f"  샘플 {len(rows)}")
        print(f"  byte 한도값 분포: {dict(limit_msgs)}")
        if url_lens:
            url_lens.sort()
            print(
                f"  이미지 URL 길이: min={url_lens[0]} max={url_lens[-1]} median={url_lens[len(url_lens) // 2]}"
            )
        print(f"  호스트: {dict(hosts.most_common(6))}")
        # 가장 긴 URL 샘플
        long_urls = sorted(
            {
                str(u)
                for r in rows
                for u in (
                    json.loads(r.images)
                    if isinstance(r.images, str)
                    else (r.images or [])
                )
            },
            key=len,
            reverse=True,
        )[:3]
        for u in long_urls:
            print(f"    len={len(u)} {u[:110]}")

        # ── 11번가 키속성 ──
        print("\n" + "=" * 60)
        print("[11번가 키속성 누락]")
        rows2 = (
            await session.execute(
                text("""
            SELECT s.transmit_error, cp.category1, cp.category2, cp.category3, cp.options, cp.extra_data
            FROM samba_shipment s JOIN samba_collected_product cp ON cp.id=s.product_id
            WHERE s.status='failed' AND s.created_at >= now() - interval '3 days'
              AND CAST(s.transmit_error AS text) LIKE '%키속성%' ESCAPE '!'
            LIMIT 100
        """)
            )
        ).fetchall()
        # 한글 LIKE 안 먹으니 폴백: 11st + 디코드 필터
        if not rows2:
            rows2 = (
                await session.execute(
                    text("""
                SELECT s.transmit_error, cp.category1, cp.category2, cp.category3, cp.options, cp.extra_data
                FROM samba_shipment s JOIN samba_collected_product cp ON cp.id=s.product_id
                WHERE s.status='failed' AND s.created_at >= now() - interval '3 days'
                  AND EXISTS (SELECT 1 FROM samba_market_account ma WHERE ma.market_type='11st'
                              AND CAST(s.target_account_ids AS text) LIKE '%'||ma.id||'%')
                LIMIT 3000
            """)
                )
            ).fetchall()
        cat_cnt = Counter()
        attr_kw = Counter()
        n2 = 0
        examples = []
        for r in rows2:
            te = r.transmit_error
            if isinstance(te, str):
                try:
                    te = json.loads(te)
                except Exception:
                    te = {"_": te}
            msg = (
                " ".join(str(v) for v in te.values())
                if isinstance(te, dict)
                else str(te)
            )
            if "키속성 정보는 반드시" not in msg:
                continue
            n2 += 1
            cat_cnt[f"{r.category1}>{r.category2}>{r.category3}"] += 1
            m = re.search(r"([가-힣A-Za-z]+):\s*키속성", msg)
            if m:
                attr_kw[m.group(1)] += 1
            if len(examples) < 5:
                examples.append(
                    (
                        f"{r.category1}>{r.category2}>{r.category3}",
                        m.group(1) if m else "?",
                        r.options,
                    )
                )
        print(f"  매칭 {n2}")
        print(f"  누락 키속성명: {dict(attr_kw.most_common())}")
        print(f"  카테고리: {dict(cat_cnt.most_common(8))}")
        for cat, kw, attrs in examples:
            a = attrs
            if isinstance(a, str):
                try:
                    a = json.loads(a)
                except Exception:
                    a = a[:80]
            print(f"    [{kw}] {cat} | attrs={str(a)[:120]}")


if __name__ == "__main__":
    asyncio.run(main())
