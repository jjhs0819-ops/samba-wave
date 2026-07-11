"""롯데홈쇼핑 유령상품 일일 자동 진단.

매일 1회 롯데홈쇼핑 재고목록(searchStockList)을 스트리밍 수신해
우리 DB market_product_nos 와 대조한다.

**중요(2026-07-10 실측 교훈)**: 롯데홈 searchStockList 는 판매중 전량을
반환하지 않는 **부분집합**이다(포털 판매중 51,569 vs API 덤프 판매진행 31,704).
그래서 "덤프에 없음"을 죽은기록으로 판정하면 실제 판매중 상품을 오삭제한다.
따라서 이 리컨실러는 **덤프에 실존하는 상품만** 신뢰해 두 종류만 감지한다:

  ① 유령(ghost)      : 덤프에서 판매진행(SaleStatCd=10)인데 DB 매핑 없음
  ② 죽은기록(stale)  : DB 매핑인데 덤프에서 품절(20)/영구중단(30)

둘 다 monitor_event(lottehome_ghost_detected)로 알림만 기록한다.
자동 정리는 LOTTEHOME_AUTO_END_GHOSTS=1 일 때만(기본 OFF, 알림 전용).
전량 정밀 대조가 필요하면 파트너오피스 판매중 목록이 유일 신뢰 소스이며,
그 작업은 수동 운영 절차로 남긴다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

import httpx
from sqlalchemy import text

from backend.db.orm import get_write_session
from backend.domain.samba.proxy.lottehome import LotteHomeClient
from backend.shutdown_state import is_shutting_down


logger = logging.getLogger("backend.lottehome.ghost_reconciler")

# 운영 파라미터
RUN_INTERVAL_SECONDS = 24 * 3600  # 하루 1회
INITIAL_DELAY_SECONDS = 60 * 35  # 부팅 35분 뒤 첫 실행(롯데온 리컨실러와 시차)
ALERT_THRESHOLD = 100  # 유령 N개 초과 시 강한 알림
STREAM_TIMEOUT = 900  # searchStockList 전량 스트리밍(실측 106MB/86s)
AUTO_END = os.environ.get("LOTTEHOME_AUTO_END_GHOSTS", "").lower() in (
    "1",
    "true",
    "yes",
)
END_BATCH_DELAY = 0.3

# 재고목록 XML 행: <GoodNo>..</GoodNo>...<SaleStatCd>NN</SaleStatCd>
# GoodsNm 뒤에 나오므로 GoodNo→SaleStatCd 사이를 non-greedy 로 매칭.
_ROW_RE = re.compile(rb"<GoodNo>(\d+)</GoodNo>.*?<SaleStatCd>(\d+)</SaleStatCd>", re.S)


async def _fetch_active_lottehome_accounts() -> list[dict[str, Any]]:
    async with get_write_session() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT id, account_label, seller_id, tenant_id "
                        "FROM samba_market_account "
                        "WHERE market_type='lottehome' AND is_active=true"
                    )
                )
            )
            .mappings()
            .all()
        )
    return [dict(r) for r in rows]


async def _get_client_for(tenant_id: str | None) -> LotteHomeClient | None:
    """계정 tenant 기준 lottehome_credentials 로 클라이언트 생성."""
    from backend.api.v1.routers.samba.proxy._helpers import _get_setting

    async with get_write_session() as session:
        creds = await _get_setting(
            session, "lottehome_credentials", tenant_id=tenant_id
        )
    if isinstance(creds, str):
        try:
            creds = json.loads(creds)
        except Exception:
            creds = {}
    if not isinstance(creds, dict) or not creds.get("userId"):
        return None
    return LotteHomeClient(
        user_id=creds.get("userId", ""),
        password=creds.get("password", ""),
        agnc_no=creds.get("agncNo", ""),
        env=creds.get("env", "prod"),
    )


# 매핑 값에서 goods_no 후보 추출 — 정상은 순수 숫자 문자열이지만, 타 마켓에서
# dict/list 로 깨진 행이 실재했으므로(11번가 #578) 숫자 시퀀스 전부 수확한다.
# 유령 판정의 보호셋이므로 과다포함이 과소포함보다 안전하다(놓치면 실상품 오중단).
_DIGITS_RE = re.compile(r"\d{6,}")


async def _fetch_db_mapping(account_id: str) -> tuple[set[str], set[str]]:
    """이 계정에 매핑된 goods_no 집합 반환: (전체, 그중 삼바 품절 상태).

    승인대기 _qa 키는 'pending'/'approved' 상태 문자열이고 goods_no 는
    본키에 저장되므로 본키만 보면 승인 전/후 모두 잡힌다(#480 구조).
    """
    async with get_write_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT market_product_nos->>:aid, sale_status "
                    "FROM samba_collected_product "
                    "WHERE market_product_nos ? :aid"
                ),
                {"aid": account_id},
            )
        ).all()
    all_gnos: set[str] = set()
    soldout_gnos: set[str] = set()
    for v, sale_status in rows:
        s = str(v or "").strip()
        gnos = [s] if s.isdigit() else _DIGITS_RE.findall(s)
        for g in gnos:
            all_gnos.add(g)
            if sale_status == "sold_out":
                soldout_gnos.add(g)
    return all_gnos, soldout_gnos


async def _stream_stocklist(client: LotteHomeClient) -> dict[str, str]:
    """searchStockList 전량 스트리밍 → {goods_no: sale_stat_cd}.

    행이 청크 경계에 걸릴 수 있어 마지막 4KB 이월. EUC-KR 바이트 그대로 정규식.
    """
    cert = await client._ensure_auth()
    base = client.PROD_BASE if client.env == "prod" else client.TEST_BASE
    url = base + "searchStockList.lotte"
    stat_of: dict[str, str] = {}
    timeout = httpx.Timeout(STREAM_TIMEOUT, connect=15)
    kw: dict[str, Any] = {"timeout": timeout}
    if client.proxy_url:
        kw["proxy"] = client.proxy_url
    async with httpx.AsyncClient(**kw) as hc:
        async with hc.stream("GET", url, params={"subscriptionId": cert}) as resp:
            if resp.status_code != 200:
                raise RuntimeError(f"searchStockList HTTP {resp.status_code}")
            tail = b""
            async for chunk in resp.aiter_bytes(1024 * 256):
                buf = tail + chunk
                for m in _ROW_RE.finditer(buf):
                    g = m.group(1).decode()
                    if g not in stat_of:
                        stat_of[g] = m.group(2).decode()
                tail = buf[-4096:]
    return stat_of


async def _log_event(
    account_id: str,
    account_label: str,
    ghosts: int,
    stale: int,
    dump_total: int,
) -> None:
    try:
        from backend.domain.samba.warroom.model import SambaMonitorEvent

        total = ghosts + stale
        async with get_write_session() as session:
            session.add(
                SambaMonitorEvent(
                    event_type="lottehome_ghost_detected",
                    severity="warning" if total < ALERT_THRESHOLD else "critical",
                    market_type="lottehome",
                    summary=(
                        f"롯데홈 {account_label} 유령 {ghosts}개 / "
                        f"죽은기록 {stale}개 감지"
                    ),
                    detail={
                        "account_id": account_id,
                        "account_label": account_label,
                        "ghosts": ghosts,
                        "stale": stale,
                        "total": total,
                        "dump_total": dump_total,
                        "auto_end_enabled": AUTO_END,
                        "note": "searchStockList 부분집합 — 덤프 실존분만 판정",
                    },
                )
            )
            await session.commit()
    except Exception as e:
        logger.debug(f"[lottehome_reconciler] monitor_event 기록 스킵: {e}")


async def _auto_end(client: LotteHomeClient, ghosts: list[str]) -> tuple[int, int]:
    """AUTO_END=on 시에만 유령 goods_no 를 영구중단(sale_stat_cd=30).

    에러 응답은 _call_api_auto_retry 가 LotteApiError 로 raise 하고,
    인증키 오류(경합 포함)는 그 안에서 자동 재인증·재시도된다.
    """
    ok = fail = 0
    for g in ghosts:
        try:
            await client.update_sale_status(g, "30")
            ok += 1
        except Exception as e:
            msg = str(e)
            # 이미 영구중단(0011)은 원하는 상태 → 성공 취급
            if "0011" in msg or "영구중단" in msg:
                ok += 1
            else:
                fail += 1
        await asyncio.sleep(END_BATCH_DELAY)
    return ok, fail


async def _reconcile_one_account(acc: dict[str, Any]) -> dict[str, Any]:
    account_id = acc["id"]
    label = acc.get("account_label") or account_id
    client = await _get_client_for(acc.get("tenant_id"))
    if client is None:
        return {"account_label": label, "skipped": "no credentials"}
    try:
        db_mapping, soldout_gnos = await _fetch_db_mapping(account_id)
        dump = await _stream_stocklist(client)

        ghost_candidates = [
            g for g, st in dump.items() if st == "10" and g not in db_mapping
        ]

        # ── 등록 경쟁 가드: 덤프 수신(~90초) 사이에 등록된 상품이 유령으로
        # 오판되지 않도록, 후보가 있으면 매핑을 재수집해 최종 확정한다.
        if ghost_candidates:
            db_mapping, soldout_gnos = await _fetch_db_mapping(account_id)
        ghosts = sorted(g for g in ghost_candidates if g not in db_mapping)

        # 죽은기록: 매핑인데 마켓 품절(20)/중단(30). 삼바도 품절로 아는
        # 상품(sold_out)은 정상 동작이므로 제외 — 알림 노이즈 방지.
        stale = sorted(
            g
            for g in db_mapping
            if dump.get(g) in ("20", "30") and g not in soldout_gnos
        )
        summary = {
            "account_label": label,
            "db_mapping": len(db_mapping),
            "dump_total": len(dump),
            "ghosts": len(ghosts),
            "stale": len(stale),
        }

        if ghosts or stale:
            sev = "WARN" if (len(ghosts) + len(stale)) < ALERT_THRESHOLD else "CRIT"
            logger.warning(
                "[lottehome_reconciler] %s %s 유령=%d 죽은기록=%d db=%d dump=%d",
                sev,
                label,
                len(ghosts),
                len(stale),
                len(db_mapping),
                len(dump),
            )
            await _log_event(account_id, label, len(ghosts), len(stale), len(dump))
            if AUTO_END and ghosts:
                ok, f = await _auto_end(client, ghosts)
                summary["auto_end_success"] = ok
                summary["auto_end_failed"] = f
                logger.warning(
                    "[lottehome_reconciler] %s AUTO_END success=%d failed=%d",
                    label,
                    ok,
                    f,
                )
        else:
            logger.info(
                "[lottehome_reconciler] OK %s 유령/죽은기록 없음 db=%d dump=%d",
                label,
                len(db_mapping),
                len(dump),
            )
        return summary
    finally:
        # LotteHomeClient 는 요청마다 client 생성이라 별도 close 불필요
        pass


async def reconcile_all_accounts_once() -> list[dict[str, Any]]:
    """1회 실행 — 수동 트리거/테스트용."""
    results: list[dict[str, Any]] = []
    accounts = await _fetch_active_lottehome_accounts()
    logger.info(f"[lottehome_reconciler] 대상 롯데홈 계정 {len(accounts)}개")
    for acc in accounts:
        try:
            results.append(await _reconcile_one_account(acc))
        except Exception as e:
            logger.exception(
                f"[lottehome_reconciler] {acc.get('account_label')} 실패: {e}"
            )
            results.append({"account_label": acc.get("account_label"), "error": str(e)})
    return results


async def ghost_reconciler_loop() -> None:
    """24시간 주기 백그라운드 루프 — lifecycle 에서 create_task 로 기동."""
    logger.info(
        "[lottehome_reconciler] 시작 — interval=24h, auto_end=%s, first_run_in=%ds",
        AUTO_END,
        INITIAL_DELAY_SECONDS,
    )
    await asyncio.sleep(INITIAL_DELAY_SECONDS)
    while not is_shutting_down():
        try:
            await reconcile_all_accounts_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(
                f"[lottehome_reconciler] cycle 실패(다음 cycle 재시도): {e}"
            )
        slept = 0
        while slept < RUN_INTERVAL_SECONDS and not is_shutting_down():
            await asyncio.sleep(min(60, RUN_INTERVAL_SECONDS - slept))
            slept += 60
