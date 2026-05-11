"""롯데ON 유령상품 진단 — 셀러센터엔 있고 우리 DB엔 없는 spdNo 추출.

계정: 환경변수 LOTTEON_ACCOUNT_LABEL (기본값: 'unclehg') 의 LOTTEON 마켓계정.
출력: /tmp/lotteon_ghosts_<account_label>.json
"""

import asyncio
import asyncpg
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, "/app/backend")

from backend.core.config import settings
from backend.domain.samba.proxy.lotteon import LotteonClient


PAGE_SIZE = 200
# 등록일 범위 — 충분히 넓게
REG_START = "20200101000000"
REG_END = datetime.now().strftime("%Y%m%d235959")


async def fetch_lotteon_account(conn, label: str) -> dict:
  """LOTTEON 계정 1건 조회 (seller_id 또는 account_label 부분일치)."""
  row = await conn.fetchrow(
    """
    SELECT id, account_label, seller_id, api_key, additional_fields
    FROM samba_market_account
    WHERE market_type = 'lotteon'
      AND is_active = true
      AND (seller_id = $1 OR account_label = $1 OR account_label ILIKE '%' || $1 || '%')
    ORDER BY created_at
    LIMIT 1
    """,
    label,
  )
  if not row:
    print(f"[ERROR] LOTTEON 계정 '{label}' 없음")
    sys.exit(1)
  return dict(row)


async def fetch_db_known_spd_nos(conn, account_id: str) -> set[str]:
  """우리 DB에서 해당 계정으로 등록된 spdNo 집합."""
  rows = await conn.fetch(
    """
    SELECT market_product_nos
    FROM samba_collected_product
    WHERE market_product_nos IS NOT NULL
      AND market_product_nos ? $1
    """,
    account_id,
  )
  spd_set: set[str] = set()
  for r in rows:
    mpn = r["market_product_nos"] or {}
    if isinstance(mpn, str):
      try:
        mpn = json.loads(mpn)
      except Exception:
        mpn = {}
    if not isinstance(mpn, dict):
      continue
    v = mpn.get(account_id) or mpn.get(f"{account_id}_origin")
    if v is None:
      continue
    spd_set.add(str(v).strip())
  return {s for s in spd_set if s}


async def fetch_lotteon_all_products(client: LotteonClient) -> list[dict]:
  """list_registered_products 전체 페이지 수집."""
  await client.test_auth()
  all_items: list[dict] = []
  page = 1
  while True:
    resp = await client.list_registered_products(
      page=page,
      size=PAGE_SIZE,
      reg_strt_dttm=REG_START,
      reg_end_dttm=REG_END,
    )
    data = resp.get("data") or {}
    # 응답 키 추정 — 실제 키 확인 후 보정
    items = (
      data.get("spdLst")
      or data.get("prdLst")
      or data.get("prdList")
      or data.get("list")
      or []
    )
    if not isinstance(items, list):
      items = []
    print(f"  page={page} size={PAGE_SIZE} → {len(items)}개")
    all_items.extend(items)
    if len(items) < PAGE_SIZE:
      break
    page += 1
    if page > 200:
      print("  [WARN] 200페이지 초과 — 중단")
      break
  return all_items


async def main():
  label = os.environ.get("LOTTEON_ACCOUNT_LABEL", "unclehg")
  conn = await asyncpg.connect(
    host=settings.write_db_host,
    port=settings.write_db_port,
    ssl=False,
    database=settings.write_db_name,
    user=settings.write_db_user,
    password=settings.write_db_password,
  )

  acc = await fetch_lotteon_account(conn, label)
  account_id = acc["id"]
  api_key = (acc.get("api_key") or "").strip()
  if not api_key:
    addl = acc.get("additional_fields") or {}
    if isinstance(addl, str):
      try:
        addl = json.loads(addl)
      except Exception:
        addl = {}
    api_key = (addl or {}).get("apiKey", "") or ""
  if not api_key:
    print(f"[ERROR] {label} api_key 없음")
    sys.exit(1)
  print(f"[INFO] account_label={label} id={account_id} api_key={api_key[:8]}***")

  print("[INFO] DB known spdNo 수집 중...")
  db_spds = await fetch_db_known_spd_nos(conn, account_id)
  print(f"[INFO] DB known = {len(db_spds):,}개")

  print("[INFO] 롯데ON list_registered_products 전체 페이지 수집 중...")
  client = LotteonClient(api_key)
  try:
    lotteon_items = await fetch_lotteon_all_products(client)
  finally:
    await client.aclose()
  print(f"[INFO] LOTTEON total = {len(lotteon_items):,}개")

  # spdNo 추출 (응답 키 후보 다중 대응)
  lotteon_spds: dict[str, dict] = {}
  for it in lotteon_items:
    if not isinstance(it, dict):
      continue
    spd = it.get("spdNo") or it.get("prdNo") or it.get("epdNo") or ""
    spd = str(spd).strip()
    if spd:
      lotteon_spds[spd] = it

  ghosts = [
    {"spdNo": k, **lotteon_spds[k]}
    for k in lotteon_spds.keys() - db_spds
  ]
  missing_on_market = sorted(db_spds - set(lotteon_spds.keys()))

  out_path = f"/tmp/lotteon_ghosts_{label}.json"
  with open(out_path, "w", encoding="utf-8") as f:
    json.dump(
      {
        "account_label": label,
        "account_id": account_id,
        "stats": {
          "db_known": len(db_spds),
          "lotteon_total": len(lotteon_spds),
          "ghosts": len(ghosts),
          "missing_on_market": len(missing_on_market),
        },
        "ghosts": ghosts,
        "missing_on_market_sample": missing_on_market[:50],
      },
      f,
      ensure_ascii=False,
      indent=2,
    )

  print()
  print("===== 결과 요약 =====")
  print(f"  DB known          : {len(db_spds):,}")
  print(f"  LOTTEON total     : {len(lotteon_spds):,}")
  print(f"  유령(LOTTEON only): {len(ghosts):,}")
  print(f"  반대로 DB only    : {len(missing_on_market):,}")
  print(f"  출력: {out_path}")

  await conn.close()


asyncio.run(main())
