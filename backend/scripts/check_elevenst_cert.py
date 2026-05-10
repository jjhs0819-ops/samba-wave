"""11번가 등록상품의 KC인증 필드 raw 값 점검용 일회성 스크립트.

prdNo 1건을 GET /rest/prodservices/product/{prdNo} 로 조회한 뒤
crtfGrpObjClfCd01~04 값을 출력. API 키는 화면에 노출하지 않음.
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


async def main() -> None:
    if len(sys.argv) < 2:
        print("usage: check_elevenst_cert.py <prdNo>")
        sys.exit(2)
    prd_no = sys.argv[1].strip()

    # 프로덕션은 /cloudsql/ 유닉스소켓 / 로컬은 host:port — orm._build_db_url 재사용
    from backend.db.orm import _build_db_url

    url = _build_db_url(
        settings.write_db_user,
        settings.write_db_password,
        settings.write_db_host,
        settings.write_db_port,
        settings.write_db_name,
    )
    engine = create_async_engine(url, echo=False)
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT id, account_label, api_key, additional_fields "
                    "FROM samba_market_account "
                    "WHERE market_type='11st' AND is_active=true "
                    "ORDER BY created_at DESC LIMIT 1"
                )
            )
        ).fetchone()
    await engine.dispose()
    if not row:
        print("[ERR] 11번가 활성 계정 없음")
        sys.exit(1)
    acc_id, label, raw_key, extras = row
    extras = extras or {}
    print(f"[DBG] extras keys = {list(extras.keys())}")
    print(f"[DBG] raw_key set = {bool(raw_key)}")
    for k, v in extras.items():
        if isinstance(v, str) and len(v) > 8:
            print(f"  extras[{k}] = ****{v[-4:]} (len={len(v)})")
        else:
            print(f"  extras[{k}] = {v!r}")
    api_key = (extras.get("apiKey") or raw_key or "").strip()
    if not api_key:
        print("[ERR] api_key 없음")
        sys.exit(1)
    print(f"[ACC] id={acc_id} label={label} key=****{api_key[-4:]}")

    # 동일 계정으로 등록된 11번가 prdNo 1건 추출 (검증용)
    from backend.db.orm import _build_db_url as _bd
    engine2 = create_async_engine(_bd(settings.write_db_user, settings.write_db_password, settings.write_db_host, settings.write_db_port, settings.write_db_name), echo=False)
    async with engine2.connect() as c2:
        r2 = (await c2.execute(text(
            "SELECT id, market_product_nos FROM samba_collected_product "
            "WHERE market_product_nos::text LIKE :acc "
            "ORDER BY updated_at DESC LIMIT 5"
        ), {"acc": f"%{acc_id}%"})).fetchall()
    await engine2.dispose()
    print(f"\n[등록 prdNo 후보 — {len(r2)}건]")
    candidate_prds = []
    for cp_id, mpn in r2:
        if isinstance(mpn, str):
            try:
                mpn = json.loads(mpn)
            except Exception:
                continue
        if isinstance(mpn, dict):
            v = mpn.get(acc_id)
            if v and str(v).isdigit():
                print(f"  cp={cp_id} prdNo={v}")
                candidate_prds.append(str(v))
    if candidate_prds:
        prd_no = candidate_prds[0]
        print(f"\n[교체] prd_no → 등록된 prdNo {prd_no} 로 검증 진행")

    # 프로젝트 클라이언트로 정식 호출 (헤더/엔드포인트 정확)
    cli = ElevenstClient(api_key=api_key)
    print("\n[AUTH TEST get_categories]")
    try:
        cat = await cli.get_categories()
        print(f"  OK keys={list(cat.keys())[:3] if isinstance(cat, dict) else type(cat)}")
    except Exception as e:
        print(f"  FAIL: {str(e)[:200]}")

    print("\n[GET via ElevenstClient.get_product]")
    try:
        d = await cli.get_product(prd_no)
        raw = d.get("raw", "") if isinstance(d, dict) else ""
        print(f"  OK keys={list(d.keys())[:10] if isinstance(d, dict) else type(d)}")
        print(f"  raw_len={len(raw)}")
        for tag in ("crtfGrpObjClfCd01","crtfGrpObjClfCd02","crtfGrpObjClfCd03","crtfGrpObjClfCd04"):
            m = re.search(rf"<{tag}>([^<]*)</{tag}>", raw)
            print(f"  {tag} = {m.group(1) if m else '(없음)'}")
    except Exception as e:
        print(f"  FAIL: {str(e)[:300]}")

    sys.exit(0)
    import httpx
    headers = {
        "openapikey": api_key,
        "Accept": "application/xml; charset=utf-8",
    }
    paths = [
        f"https://api.11st.co.kr/rest/prodservices/product/{prd_no}",
        f"https://api.11st.co.kr/rest/prodservices/prod/{prd_no}",
        f"https://api.11st.co.kr/rest/selprodservices/prodsearch/{prd_no}",
        f"https://api.11st.co.kr/rest/selprodservice/prdservice/{prd_no}",
        f"https://api.11st.co.kr/rest/prodservices/sellerProduct/{prd_no}",
    ]
    async with httpx.AsyncClient(timeout=15) as client:
        for p in paths:
            try:
                r = await client.get(p, headers=headers)
                snippet = r.text[:300].replace("\n", " ")
                print(f"\n[GET {p}] → {r.status_code}\n  {snippet}")
            except Exception as e:
                print(f"[GET {p}] FAIL {e}")
    sys.exit(0)
    cli = ElevenstClient(api_key=api_key)
    try:
        data = await cli.get_product(prd_no)
    except Exception as e:
        print(f"[ERR] get_product 실패: {e}")
        sys.exit(1)

    print("\n[response keys]")
    if isinstance(data, dict):
        for k in list(data.keys())[:60]:
            print(f"  - {k}")
    else:
        print(f"  type={type(data)}")

    print("\n[crtfGrpObjClfCd 추출]")
    raw = data.get("raw", "") if isinstance(data, dict) else ""
    if not raw:
        # raw 가 없으면 dict 자체에서 키 검색
        for k in ("crtfGrpObjClfCd01", "crtfGrpObjClfCd02", "crtfGrpObjClfCd03", "crtfGrpObjClfCd04"):
            print(f"  {k} = {data.get(k) if isinstance(data, dict) else 'N/A'}")
    else:
        for tag in ("crtfGrpObjClfCd01", "crtfGrpObjClfCd02", "crtfGrpObjClfCd03", "crtfGrpObjClfCd04"):
            m = re.search(rf"<{tag}>([^<]*)</{tag}>", raw)
            print(f"  {tag} = {m.group(1) if m else '(없음)'}")

    print("\n[전체 응답 XML 일부 (앞 1500자)]")
    if isinstance(data, dict):
        sample = data.get("raw", "") or str(data)[:1500]
        print(sample[:1500])


if __name__ == "__main__":
    asyncio.run(main())
