"""미등록 주문 소급 매칭 스크립트.

대상:
  - PlayAuto 주문 (source='playauto') — 신규 3.8 style_code 매칭
  - lottehome 주문 — 기존 style_code 매칭 누락분

실행:
  VM: sudo docker cp backfill_unreg_orders.py samba-samba-api-1:/tmp/
      sudo docker exec samba-samba-api-1 /app/backend/.venv/bin/python3 /tmp/backfill_unreg_orders.py
"""

import asyncio
import json
import re
import sys

import asyncpg


# ── 설정 ──────────────────────────────────────────────────────────────────────
sys.path.insert(0, "/app/backend")
from backend.core.config import settings  # noqa: E402

_DB_HOST = settings.write_db_host  # 'cloud-sql-proxy'
_DB_PORT = int(settings.write_db_port)
_DB_USER = settings.write_db_user
_DB_PASS = settings.write_db_password
_DB_NAME = settings.write_db_name

_STYLE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


def _style_tokens(name: str) -> list[str]:
    return [
        t
        for t in _STYLE_TOKEN_RE.findall(name or "")
        if len(t) >= 6 and any(c.isdigit() for c in t)
    ]


async def main() -> None:
    conn = await asyncpg.connect(
        host=_DB_HOST, port=_DB_PORT,
        user=_DB_USER, password=_DB_PASS,
        database=_DB_NAME, ssl=False,
    )
    print("DB 연결 완료")

    # 미등록 주문 조회 (playauto + lottehome)
    rows = await conn.fetch(
        """
        SELECT id, tenant_id, channel_id, product_id, product_name, source
        FROM samba_order
        WHERE collected_product_id IS NULL
          AND source IN ('playauto', 'lottehome')
          AND product_name IS NOT NULL
          AND product_name <> ''
          AND channel_id IS NOT NULL
        ORDER BY created_at DESC
        """
    )
    print(f"미등록 주문 대상: {len(rows):,}건")

    updated = 0
    skipped_multi = 0
    skipped_no_token = 0
    skipped_no_match = 0

    for row in rows:
        order_id = str(row["id"])
        channel_id = str(row["channel_id"])
        product_name = row["product_name"] or ""
        source = row["source"] or ""

        tokens = _style_tokens(product_name)
        if not tokens:
            skipped_no_token += 1
            continue

        # channel 등록 상품 단일 후보 조회
        cp_rows = await conn.fetch(
            """
            SELECT id, source_site, source_url, (images->>0) AS thumb,
                   category, style_code, cost
            FROM samba_collected_product
            WHERE registered_accounts @> CAST($1 AS jsonb)
              AND style_code = ANY($2)
            """,
            json.dumps([channel_id]),
            tokens,
        )

        cp_ids = {str(r["id"]) for r in cp_rows}

        if len(cp_ids) == 0:
            # 채널 등록 없으면 글로벌 단일 후보 시도
            cp_rows_gl = await conn.fetch(
                """
                SELECT id, source_site, source_url, (images->>0) AS thumb,
                       category, style_code, cost
                FROM samba_collected_product
                WHERE style_code = ANY($1)
                """,
                tokens,
            )
            cp_ids = {str(r["id"]) for r in cp_rows_gl}
            if len(cp_ids) == 1:
                cp_rows = cp_rows_gl
            else:
                if len(cp_ids) > 1:
                    skipped_multi += 1
                else:
                    skipped_no_match += 1
                continue
        elif len(cp_ids) > 1:
            skipped_multi += 1
            continue

        picked = cp_rows[0]
        cp_id = str(picked["id"])
        thumb = picked["thumb"] or ""
        src_site = picked["source_site"] or ""
        src_url = picked["source_url"] or ""

        await conn.execute(
            """
            UPDATE samba_order
            SET collected_product_id = $1,
                product_image = CASE WHEN product_image IS NULL OR product_image = '' THEN $2 ELSE product_image END,
                source_site   = CASE WHEN source_site   IS NULL OR source_site   = '' THEN $3 ELSE source_site   END,
                source_url    = CASE WHEN source_url    IS NULL OR source_url    = '' THEN $4 ELSE source_url    END
            WHERE id = $5
            """,
            cp_id,
            thumb,
            src_site,
            src_url,
            row["id"],
        )
        updated += 1
        if updated % 100 == 0:
            print(f"  진행 중... {updated:,}건 완료")

    print("\n=== 결과 ===")
    print(f"  매칭 성공:     {updated:,}건")
    print(f"  토큰 없음:     {skipped_no_token:,}건")
    print(f"  다중 후보:     {skipped_multi:,}건 (오매칭 방지 skip)")
    print(f"  후보 없음:     {skipped_no_match:,}건 (미수집 또는 미전송 상품)")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
