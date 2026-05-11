"""11번가 prdNo 자동 탐색 + GET 호출 (transmit_result에서 추출)."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from backend.core.config import settings  # noqa: E402
from backend.domain.samba.proxy.elevenst import ElevenstClient  # noqa: E402


async def main() -> None:
    url = (
        f"postgresql+asyncpg://{settings.write_db_user}:{settings.write_db_password}"
        f"@{settings.write_db_host}:{settings.write_db_port}/{settings.write_db_name}"
    )
    engine = create_async_engine(url, echo=False)
    async with engine.connect() as conn:
        # 1) 11번가 계정 ID + apiKey
        acc = (
            await conn.execute(
                text(
                    "SELECT id, additional_fields FROM samba_market_account "
                    "WHERE market_type='11st' AND is_active=true ORDER BY created_at DESC LIMIT 1"
                )
            )
        ).fetchone()
        if not acc:
            print("[ERR] 11번가 계정 없음")
            sys.exit(1)
        acc_id, extras = acc
        api_key = ((extras or {}).get("apiKey") or "").strip()
        print(f"[ACC] {acc_id} key=****{api_key[-4:] if api_key else 'NONE'}")

        # 2) 해당 계정으로 전송된 11번가 shipment 중 product_no 보유 건
        rows = (
            await conn.execute(
                text(
                    "SELECT id, market_product_nos FROM samba_collected_product "
                    "WHERE market_product_nos::text LIKE :acc "
                    "ORDER BY updated_at DESC LIMIT 30"
                ),
                {"acc": f"%{acc_id}%"},
            )
        ).fetchall()
        print(f"[ROWS] {len(rows)} 건 11번가 계정 매핑된 collected_product")
    await engine.dispose()

    found = []
    for cp_id, mpn in rows:
        if isinstance(mpn, str):
            try:
                mpn = json.loads(mpn)
            except Exception:
                continue
        if not isinstance(mpn, dict):
            continue
        no = mpn.get(acc_id)
        if no and str(no).isdigit():
            found.append((cp_id, cp_id, str(no), acc_id))
            break

    if not found:
        print("[INFO] 11번가 product_no 매핑 못 찾음")
        sys.exit(2)
    sh_id, prod_id, prdno, used_acc = found[0]
    print(
        f"[FOUND] shipment={sh_id} product={prod_id} prdNo={prdno} acc_used={used_acc}"
    )

    if not api_key or not prdno:
        sys.exit(2)
    cli = ElevenstClient(api_key=api_key)
    try:
        data = await cli.get_product(prdno)
    except Exception as e:
        print(f"[ERR] get_product({prdno}) 실패: {str(e)[:300]}")
        sys.exit(1)

    raw = data.get("raw", "") if isinstance(data, dict) else ""
    src = raw or json.dumps(data, ensure_ascii=False)
    print(f"\n[GET 응답 길이] {len(src)} chars")
    print("\n[crtfGrpObjClfCd 추출]")
    for tag in (
        "crtfGrpObjClfCd01",
        "crtfGrpObjClfCd02",
        "crtfGrpObjClfCd03",
        "crtfGrpObjClfCd04",
    ):
        m = re.search(rf"<{tag}>([^<]*)</{tag}>", src)
        print(f"  {tag} = {m.group(1) if m else '(없음)'}")

    print("\n[crtf 포함 모든 태그]")
    for m in re.finditer(r"<([^/>\s]*[Cc]rtf[^/>\s]*)>([^<]*)</[^>]+>", src):
        print(f"  <{m.group(1)}> = {m.group(2)}")

    print("\n[kc/KC 포함 태그]")
    for m in re.finditer(r"<([^/>\s]*[Kk][Cc][^/>\s]*)>([^<]*)</[^>]+>", src):
        print(f"  <{m.group(1)}> = {m.group(2)}")


if __name__ == "__main__":
    asyncio.run(main())
