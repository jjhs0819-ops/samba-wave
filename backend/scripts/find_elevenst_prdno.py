"""11번가 등록된 상품 중 1건의 prdNo를 찾아 GET API로 cert 필드 raw값 출력.

registered_accounts JSON 안에 있는 11st prdNo 1개 추출 후 GET 호출.
민감정보(api_key 등) 미출력.
"""

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


def _extract_prdno(ra) -> str | None:
    if not ra:
        return None
    if isinstance(ra, str):
        try:
            ra = json.loads(ra)
        except Exception:
            return None
    if not isinstance(ra, dict):
        return None
    eleven = ra.get("11st") or ra.get("elevenst") or ra.get("11번가")
    if not eleven:
        return None
    if isinstance(eleven, dict):
        for k in ("prdNo", "productNo", "originProductNo", "id", "no"):
            v = eleven.get(k)
            if v:
                return str(v)
    if isinstance(eleven, list) and eleven:
        first = eleven[0]
        if isinstance(first, dict):
            for k in ("prdNo", "productNo", "originProductNo", "id", "no"):
                v = first.get(k)
                if v:
                    return str(v)
    if isinstance(eleven, (str, int)):
        return str(eleven)
    return None


async def main() -> None:
    url = (
        f"postgresql+asyncpg://{settings.write_db_user}:{settings.write_db_password}"
        f"@{settings.write_db_host}:{settings.write_db_port}/{settings.write_db_name}"
    )
    engine = create_async_engine(url, echo=False)
    api_key = ""
    prdno = ""
    sample_shape = ""
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT additional_fields FROM samba_market_account "
                    "WHERE market_type='11st' AND is_active=true "
                    "ORDER BY created_at DESC LIMIT 1"
                )
            )
        ).fetchone()
        if not row:
            print("[ERR] 11번가 활성 계정 없음")
            sys.exit(1)
        extras = row[0] or {}
        api_key = (extras.get("apiKey") or "").strip()

        rows = (
            await conn.execute(
                text(
                    "SELECT id, registered_accounts FROM samba_product "
                    "WHERE registered_accounts::text LIKE '%11st%' "
                    "ORDER BY updated_at DESC LIMIT 5"
                )
            )
        ).fetchall()
        for prod_id, ra in rows:
            if isinstance(ra, str):
                try:
                    ra_obj = json.loads(ra)
                except Exception:
                    ra_obj = ra
            else:
                ra_obj = ra
            print(
                f"[ROW] {prod_id} top_keys={list(ra_obj.keys()) if isinstance(ra_obj, dict) else type(ra_obj).__name__}"
            )
            if isinstance(ra_obj, dict):
                for k, v in list(ra_obj.items())[:8]:
                    if isinstance(v, dict):
                        print(f"   {k}: dict keys={list(v.keys())}")
                    elif isinstance(v, list):
                        print(
                            f"   {k}: list len={len(v)} first_keys={list(v[0].keys()) if v and isinstance(v[0], dict) else 'N/A'}"
                        )
                    else:
                        print(f"   {k}: {type(v).__name__}={str(v)[:50]}")
            no = _extract_prdno(ra)
            if not sample_shape:
                # 한 건의 11st 데이터 형태(키 목록만) 출력
                shape = ra.get("11st") if isinstance(ra, dict) else None
                if shape is None and isinstance(ra, str):
                    try:
                        shape = json.loads(ra).get("11st")
                    except Exception:
                        shape = None
                if isinstance(shape, dict):
                    sample_shape = f"dict keys={list(shape.keys())}"
                elif isinstance(shape, list) and shape:
                    sample_shape = f"list[0] keys={list(shape[0].keys()) if isinstance(shape[0], dict) else type(shape[0])}"
                else:
                    sample_shape = (
                        f"type={type(shape).__name__} value={str(shape)[:80]}"
                    )
            if no:
                prdno = no
                print(
                    f"[FOUND] product_id={prod_id} prdNo={prdno} sample_shape={sample_shape}"
                )
                break
        else:
            print(
                f"[INFO] 11st 매핑 5건 모두 prdNo 추출 실패. 첫 건 shape: {sample_shape}"
            )
    await engine.dispose()

    if not api_key or not prdno:
        sys.exit(2)

    cli = ElevenstClient(api_key=api_key)
    try:
        data = await cli.get_product(prdno)
    except Exception as e:
        print(f"[ERR] get_product({prdno}) 실패: {str(e)[:300]}")
        sys.exit(1)

    raw = data.get("raw", "") if isinstance(data, dict) else ""
    print("\n[crtfGrpObjClfCd raw]")
    src = raw or json.dumps(data, ensure_ascii=False)
    for tag in (
        "crtfGrpObjClfCd01",
        "crtfGrpObjClfCd02",
        "crtfGrpObjClfCd03",
        "crtfGrpObjClfCd04",
    ):
        m = re.search(rf"<{tag}>([^<]*)</{tag}>", src)
        print(f"  {tag} = {m.group(1) if m else '(없음)'}")

    print("\n[키워드 추출 — 인증 관련]")
    for kw in ("crtf", "kc", "Crtf", "CRTF"):
        for m in re.finditer(rf"<([^/>]*{kw}[^/>]*)>([^<]*)</[^>]+>", src):
            print(f"  <{m.group(1)}> = {m.group(2)}")


if __name__ == "__main__":
    asyncio.run(main())
