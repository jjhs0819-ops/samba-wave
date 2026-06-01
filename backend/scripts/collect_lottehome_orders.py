"""롯데홈쇼핑 주문 직접 수집 스크립트 (VM 컨테이너 실행용)."""
import asyncio
import json
from datetime import UTC, datetime, timedelta

import asyncpg

from backend.core.config import settings
from backend.domain.samba.proxy.lottehome import LotteHomeClient


async def main() -> None:
    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )

    row = await conn.fetchrow(
        "SELECT value FROM samba_settings WHERE key = 'lottehome_credentials'"
    )
    if not row:
        print("[오류] lottehome_credentials 설정 없음")
        await conn.close()
        return

    creds = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
    user_id = creds.get("userId", "")
    password = creds.get("password", "")
    agnc_no = creds.get("agncNo", "")
    env = creds.get("env", "prod")

    # collect 용도 프록시 조회
    proxy_rows = await conn.fetch(
        "SELECT value FROM samba_settings WHERE key = 'proxy_list'"
    )
    proxy_url = None
    for pr in proxy_rows:
        val = json.loads(pr["value"]) if isinstance(pr["value"], str) else pr["value"]
        items = val if isinstance(val, list) else []
        for p in items:
            if isinstance(p, dict) and p.get("active"):
                purposes = p.get("purpose") or p.get("purposes") or []
                if isinstance(purposes, str):
                    purposes = [purposes]
                if "collect" in purposes:
                    proxy_url = p.get("url")
                    break
        if proxy_url:
            break

    print(f"[정보] userId={user_id}, env={env}, proxy={proxy_url or '없음(직접연결)'}")

    client = LotteHomeClient(user_id, password, agnc_no, env, proxy_url=proxy_url)

    end_dt = datetime.now(UTC)
    start_dt = end_dt - timedelta(days=2)
    start_str = start_dt.strftime("%Y%m%d")
    end_str = end_dt.strftime("%Y%m%d")

    total = 0
    for sel_option in ["01", "02", "03"]:
        try:
            orders = await client.search_new_orders(start_str, end_str, sel_option=sel_option)
            print(f"[sel_option={sel_option}] {len(orders)}건")
            total += len(orders)
            for o in orders[:5]:
                prod = o.get("ProdInfo", {}) if isinstance(o.get("ProdInfo"), dict) else {}
                oid = str(
                    o.get("SubOrdNo")
                    or prod.get("DlvUnitSn")
                    or prod.get("OrdDtlSn")
                    or o.get("OrdNo", "")
                    or ""
                )
                print(f"  주문번호: {oid}")
        except Exception as e:
            print(f"[sel_option={sel_option}] 오류: {e}")

    print(f"\n[완료] 총 {total}건 조회")
    await conn.close()


asyncio.run(main())
