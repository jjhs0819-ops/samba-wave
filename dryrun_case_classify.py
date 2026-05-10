"""삭제 대상 중 등록상태 row(2,770건) 케이스 분류 드라이런"""

import asyncio
import asyncpg
from backend.core.config import settings


RANK_SQL = """
WITH dup_keys AS (
  SELECT COALESCE(tenant_id, '__NULL__') AS tk, source_site, site_product_id
  FROM samba_collected_product
  WHERE site_product_id IS NOT NULL AND site_product_id <> ''
  GROUP BY COALESCE(tenant_id, '__NULL__'), source_site, site_product_id
  HAVING COUNT(*) > 1
),
ranked AS (
  SELECT cp.id, cp.tenant_id, cp.source_site, cp.site_product_id, cp.name,
         cp.market_product_nos,
         CASE WHEN jsonb_typeof(cp.registered_accounts) = 'array'
              THEN jsonb_array_length(cp.registered_accounts) ELSE 0 END AS reg_cnt,
         ROW_NUMBER() OVER (
           PARTITION BY COALESCE(cp.tenant_id, '__NULL__'), cp.source_site, cp.site_product_id
           ORDER BY
             (CASE WHEN jsonb_typeof(cp.registered_accounts) = 'array'
                    AND jsonb_array_length(cp.registered_accounts) > 0
                   THEN 1 ELSE 0 END) DESC,
             (
               SELECT COUNT(*) FROM jsonb_each(
                 CASE WHEN jsonb_typeof(cp.last_sent_data::jsonb) = 'object'
                      THEN cp.last_sent_data::jsonb ELSE '{}'::jsonb END
               ) e
               WHERE (e.value->>'sale_price') ~ '^[0-9]+(\\.[0-9]+)?$'
                 AND (e.value->>'sale_price')::numeric > 0
             ) DESC,
             cp.updated_at DESC NULLS LAST,
             cp.created_at ASC NULLS LAST,
             cp.id ASC
         ) AS rnk
  FROM samba_collected_product cp
  JOIN dup_keys d
    ON COALESCE(cp.tenant_id, '__NULL__') = d.tk
   AND cp.source_site = d.source_site
   AND cp.site_product_id = d.site_product_id
)
SELECT * FROM ranked
"""


async def main():
    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )

    print("=== 케이스 분류 드라이런 ===\n")

    # 전체 그룹 단위로 가져와서 Python 단에서 비교
    # 등록상태 row를 보유한 그룹만 필터
    rows = await conn.fetch(
        f"""
        WITH r AS ({RANK_SQL})
        SELECT * FROM r
        WHERE COALESCE(tenant_id, '__NULL__') || '|' || source_site || '|' || site_product_id IN (
            SELECT COALESCE(tenant_id, '__NULL__') || '|' || source_site || '|' || site_product_id
            FROM r
            WHERE rnk > 1 AND reg_cnt > 0
        )
        ORDER BY source_site, site_product_id, rnk
        """
    )

    # 그룹핑
    groups: dict[tuple, list] = {}
    for r in rows:
        key = (r["tenant_id"], r["source_site"], r["site_product_id"])
        groups.setdefault(key, []).append(r)

    case1_count = 0  # 같은 mpn 공유 (DB만 삭제)
    case2_count = 0  # 다른 mpn 진짜 중복 (마켓 삭제 필요)
    case_mixed_count = 0  # 일부 공유, 일부 별도
    case2_market_calls: dict[str, int] = {}  # 마켓별 삭제 호출 건수
    case2_samples = []
    case1_samples = []

    import json

    def parse_mpn(v):
        if v is None:
            return {}
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return {}
        return {}

    for key, rs in groups.items():
        keep_row = next((r for r in rs if r["rnk"] == 1), None)
        del_rows = [r for r in rs if r["rnk"] > 1 and r["reg_cnt"] > 0]
        if not keep_row or not del_rows:
            continue

        keep_mpn = parse_mpn(keep_row["market_product_nos"])
        # _origin 키 제외 (스마트스토어 보조 키)
        keep_mpn_main = {
            k: str(v) for k, v in keep_mpn.items() if not k.endswith("_origin") and v
        }

        for d in del_rows:
            d_mpn = parse_mpn(d["market_product_nos"])
            d_mpn_main = {
                k: str(v) for k, v in d_mpn.items() if not k.endswith("_origin") and v
            }

            # account별로 비교
            shared_accounts = []  # 같은 mpn
            distinct_accounts = []  # 다른 mpn 또는 keep에 없는 account
            for acc, mpn in d_mpn_main.items():
                if keep_mpn_main.get(acc) == mpn:
                    shared_accounts.append(acc)
                else:
                    distinct_accounts.append((acc, mpn, keep_mpn_main.get(acc, "")))

            if not d_mpn_main:
                # 삭제 row에 mpn 없음 — DB만 삭제
                case1_count += 1
            elif distinct_accounts and not shared_accounts:
                case2_count += 1
                for acc, mpn, _ in distinct_accounts:
                    # 어느 마켓인지 확인
                    case2_market_calls[acc] = case2_market_calls.get(acc, 0) + 1
                if len(case2_samples) < 8:
                    case2_samples.append(
                        {
                            "site": d["source_site"],
                            "spid": d["site_product_id"],
                            "keep_id": keep_row["id"],
                            "del_id": d["id"],
                            "keep_mpn": keep_mpn_main,
                            "del_mpn": d_mpn_main,
                            "distinct": distinct_accounts,
                        }
                    )
            elif shared_accounts and not distinct_accounts:
                case1_count += 1
                if len(case1_samples) < 5:
                    case1_samples.append(
                        {
                            "site": d["source_site"],
                            "spid": d["site_product_id"],
                            "keep_id": keep_row["id"],
                            "del_id": d["id"],
                            "shared": shared_accounts,
                            "mpn": d_mpn_main,
                        }
                    )
            else:
                case_mixed_count += 1
                for acc, mpn, _ in distinct_accounts:
                    case2_market_calls[acc] = case2_market_calls.get(acc, 0) + 1

    total = case1_count + case2_count + case_mixed_count
    print(f"등록보유 삭제대상 row: {total}")
    print(f"  케이스 1 (mpn 공유 또는 keep과 동일) — DB만 삭제: {case1_count}")
    print(f"  케이스 2 (다른 mpn = 진짜 마켓 중복) — 마켓 삭제 필요: {case2_count}")
    print(f"  케이스 mixed (일부 공유 일부 별도): {case_mixed_count}")

    # 마켓별 삭제 호출 카운트
    print("\n=== 케이스 2 — 계정별 마켓 삭제 호출 수 (Top 20) ===")
    if case2_market_calls:
        # account_id별 → market_type 매핑은 samba_account 조회 필요
        sorted_acc = sorted(case2_market_calls.items(), key=lambda x: -x[1])[:20]
        for acc, cnt in sorted_acc:
            print(f"  {acc}: {cnt}건")
    else:
        print("  없음 (케이스 2 = 0)")

    # 표본 출력
    print("\n=== 케이스 1 표본 (최대 5개) ===")
    for s in case1_samples:
        print(f"  [{s['site']}] {s['spid']}")
        print(f"    keep={s['keep_id']} del={s['del_id']}")
        print(f"    공유 mpn: {s['mpn']}")

    print("\n=== 케이스 2 표본 (최대 8개) ===")
    for s in case2_samples:
        print(f"\n  [{s['site']}] {s['spid']}")
        print(f"    keep={s['keep_id']} mpn={s['keep_mpn']}")
        print(f"    del ={s['del_id']} mpn={s['del_mpn']}")
        for acc, mpn, keep_mpn in s["distinct"]:
            print(
                f"      ⚠ 마켓 삭제 대상: account={acc} 삭제할 mpn={mpn} (keep은 mpn={keep_mpn or '없음'})"
            )

    await conn.close()


asyncio.run(main())
