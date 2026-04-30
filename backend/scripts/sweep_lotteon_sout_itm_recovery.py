"""SOUT_ITM 잠긴 롯데ON 상품 일괄 정정 sweep.

PR #98 fix 머지 전 등록된 상품 중 itmNm 매칭 결함으로 stkQty=0 강제 →
SOUT_STK → SOUT_ITM 잠긴 상품을 정상 재고로 복구.

흐름:
1. 본인 등록 LO 상품 조회 (market_product_nos 기준)
2. get_product → SOUT_ITM 상태 확인
3. PR #98 헬퍼와 동일한 라벨 폴백으로 무신사 옵션과 매칭
4. update_stock 호출 (stkQty 정상화)
5. change_item_status 호출 (stkQty>0 옵션만 SOUT→SALE 복구)

환경변수:
- DRY_RUN (default true) — 실제 호출 없이 미리 보기
- BATCH_SIZE (default 50)
- PARALLEL (default 5)
- ACCOUNT_ID (default kzerocp7 = ma_01KNB527D97KACS0W9W2V48AT1)
"""

import asyncio
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

DRY_RUN = os.environ.get("DRY_RUN", "true").lower() != "false"
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "50"))
PARALLEL = int(os.environ.get("PARALLEL", "5"))
ACCOUNT_ID = os.environ.get("ACCOUNT_ID", "ma_01KNB527D97KACS0W9W2V48AT1")  # kzerocp7


def _norm_opt(name: str) -> str:
    s = (name or "").strip()
    s = re.sub(r"\s*/\s*", "/", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _pick_lotteon_itm_label(itm: dict) -> str:
    """PR #98 _pick_lotteon_itm_label과 동일 — itmNm > sitmNm > optVal > optNm 폴백."""
    candidates = [itm.get("itmNm"), itm.get("sitmNm")]
    opt_lst = itm.get("itmOptLst") or []
    if opt_lst and isinstance(opt_lst[0], dict):
        candidates.append(opt_lst[0].get("optVal"))
    candidates.append(itm.get("optNm"))
    for c in candidates:
        if c is None:
            continue
        s = str(c).strip()
        if s:
            return s
    return ""


async def recover_one(client, pid, name, spd, options, dry_run=True):
    try:
        prod_resp = await client.get_product(spd)
        inner = prod_resp.get("data", prod_resp)
        if isinstance(inner, dict):
            spd_info = inner.get("spdLst") or inner.get("spdInfo") or inner
            if isinstance(spd_info, list) and spd_info:
                spd_info = spd_info[0]
        else:
            return pid, "skip_no_spd_info", None

        sl_stat_rsn = spd_info.get("slStatRsnCd")
        if sl_stat_rsn != "SOUT_ITM":
            return pid, f"skip_not_sout_itm({sl_stat_rsn or 'SALE'})", None

        itm_lst = spd_info.get("itmLst") or []
        if not itm_lst:
            return pid, "skip_no_itm", None

        opt_info_map = {
            _norm_opt(o.get("name") or ""): (
                o.get("stock", 0) or 0,
                bool(o.get("isSoldOut", False)),
            )
            for o in options
        }

        itm_stk_lst = []
        positive_count = 0
        match_count = 0
        for itm in itm_lst:
            sitm_no = itm.get("sitmNo") or itm.get("itmNo")
            if not sitm_no:
                continue
            label = _norm_opt(_pick_lotteon_itm_label(itm))
            if label in opt_info_map:
                raw_stk, sold = opt_info_map[label]
                stk = 0 if sold else max(int(raw_stk or 0), 0)
                match_count += 1
            else:
                stk = 0
            if stk > 0:
                positive_count += 1
            itm_stk_lst.append(
                {
                    "sitmNo": str(sitm_no),
                    "spdNo": spd,
                    "trNo": client.tr_no,
                    "trGrpCd": client.tr_grp_cd or "SR",
                    "stkQty": stk,
                }
            )

        if match_count == 0:
            return pid, "skip_no_match", None
        if positive_count == 0:
            return pid, "skip_all_sold_in_db", None

        if dry_run:
            return (
                pid,
                f"dry_run_match={match_count}/{len(itm_lst)}_recoverable={positive_count}",
                None,
            )

        try:
            await client.update_stock(itm_stk_lst)
        except Exception as e:
            return pid, "fail_update_stock", f"{type(e).__name__}: {str(e)[:100]}"

        to_recover = [
            {"sitmNo": s["sitmNo"], "spdNo": spd, "slStatCd": "SALE"}
            for s in itm_stk_lst
            if int(s.get("stkQty") or 0) > 0
        ]
        if to_recover:
            try:
                await client.change_item_status(to_recover)
            except Exception as e:
                return pid, "fail_change_status", f"{type(e).__name__}: {str(e)[:100]}"

        # ── SPD phase ─────────────────────────────────────────────────────
        # 옵션 SALE 복구만으로는 SPD 헤더 SOUT/SOUT_ITM이 자동 해제되지 않아 소비자
        # 페이지에서 '품절된 상품입니다'가 유지된다(2026-04-30 LO2665417627 사례).
        # product/status/change로 SPD 단위 SALE 전환 필요.
        spd_status: str = "spd_skipped"
        try:
            from backend.domain.samba.plugins.markets.lotteon import LotteonPlugin

            re_resp = await client.get_product(spd)
            re_info = LotteonPlugin._parse_lotteon_spd_info(re_resp)
            if (
                re_info.get("slStatCd") == "SOUT"
                and re_info.get("slStatRsnCd") == "SOUT_ITM"
                and any(
                    isinstance(it, dict)
                    and it.get("slStatCd") == "SALE"
                    and int(it.get("stkQty") or 0) > 0
                    for it in (re_info.get("itmLst") or [])
                )
            ):
                spd_result = await client.change_status(
                    [{"spdNo": spd, "slStatCd": "SALE"}]
                )
                ok, msg = LotteonPlugin._verify_change_status_response(spd_result)
                spd_status = "spd_recovered" if ok else f"spd_failed({msg[:40]})"
        except Exception as e:
            spd_status = f"spd_exception({type(e).__name__})"

        return (
            pid,
            f"success_match={match_count}/{len(itm_lst)}_recovered={len(to_recover)}_{spd_status}",
            None,
        )

    except Exception as e:
        return pid, "exception", f"{type(e).__name__}: {str(e)[:200]}"


async def main():
    from backend.db.orm import get_read_session
    from backend.domain.samba.plugins.markets.lotteon import _get_cached_client
    from sqlalchemy import text

    print(f"=== SOUT_ITM Sweep ({'DRY RUN' if DRY_RUN else 'EXECUTE'}) ===")
    print(f"BATCH_SIZE: {BATCH_SIZE}, PARALLEL: {PARALLEL}, ACCOUNT: {ACCOUNT_ID}")

    async with get_read_session() as session:
        r = await session.execute(
            text(
                """
            SELECT id, name, options, market_product_nos
            FROM samba_collected_product
            WHERE market_product_nos::text LIKE :acc_pattern
              AND market_product_nos::text LIKE '%LO26%'
            ORDER BY id DESC
            LIMIT :batch
            """
            ),
            {"acc_pattern": f"%{ACCOUNT_ID}%", "batch": BATCH_SIZE},
        )
        products = []
        for row in r.fetchall():
            pid, name, opts, mno = row
            opts = json.loads(opts) if isinstance(opts, str) else (opts or [])
            mno_d = json.loads(mno) if isinstance(mno, str) else (mno or {})
            spd = mno_d.get(ACCOUNT_ID)
            if spd and spd.startswith("LO"):
                products.append((pid, name, spd, opts))

        r2 = await session.execute(
            text(
                "SELECT api_key, additional_fields FROM samba_market_account WHERE id=:aid"
            ),
            {"aid": ACCOUNT_ID},
        )
        acc = r2.fetchone()
        api_key = acc[0]
        if not api_key:
            extras = acc[1] or {}
            if isinstance(extras, str):
                extras = json.loads(extras)
            api_key = extras.get("apiKey", "")

    print(f"\n[대상] {len(products)}건 LO 등록 상품 (조회 한도 {BATCH_SIZE})")

    client = await _get_cached_client(api_key)
    sem = asyncio.Semaphore(PARALLEL)

    async def _bounded(p):
        async with sem:
            return await recover_one(client, p[0], p[1], p[2], p[3], dry_run=DRY_RUN)

    results = await asyncio.gather(*(_bounded(p) for p in products))

    counters = {}
    for _, st, _ in results:
        key = st.split("_")[0] if "_" in st else st
        counters[key] = counters.get(key, 0) + 1

    print("\n=== 결과 통계 ===")
    for k, v in sorted(counters.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}건")

    sout_itm_recoverable = [
        r for r in results if r[1].startswith("dry_run") or r[1].startswith("success")
    ]
    print("\n=== SOUT_ITM 정정 대상 샘플 (최대 10건) ===")
    for p, s, m in sout_itm_recoverable[:10]:
        print(f"  {p[:32]} | {s}")

    fails = [
        r for r in results if r[1].startswith("fail") or r[1].startswith("exception")
    ]
    if fails:
        print("\n=== 실패 샘플 (최대 5건) ===")
        for p, s, m in fails[:5]:
            print(f"  {p[:32]} | {s} | {m or ''}")


if __name__ == "__main__":
    asyncio.run(main())
