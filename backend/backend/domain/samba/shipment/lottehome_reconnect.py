"""롯데홈쇼핑 전송 전 유령 재연결 가드 — 중복 리스팅 예방.

매핑(market_product_nos[account]) 없는 상품을 롯데홈에 전송하면 무조건
register_goods(신규 발급) 경로를 타는데, 과거 매핑 유실(7/13 유령 등록해제,
등록응답 유실 등)로 실제로는 판매진행 리스팅이 살아있는 상품이면 같은 상품이
마켓에 2개 등록된다(실측 2026-07-23: 에잇세컨즈 판매진행 4,112건 중
중복 리스팅 677건 — 삼바가 모르는 쪽으로 주문 유입 위험).

전송잡 시작 시 매핑 없는 롯데홈 대상 상품이 있으면 재고목록(searchStockList)을
계정당 1회 스트리밍해 backfill-goodsno 와 같은 규칙으로 기존 리스팅을 재연결한다:

- 판매진행(SaleStatCd=10) 리스팅만 재연결 (품절/중단은 재연결 이득 없음)
- 상품명 끝 숫자토큰(5자리+) == site_product_id 정확일치만
  (이름 유사도 매칭 금지 — 오연결 = 남의 리스팅에 주문·재고 위임 사고)
- 같은 상품에 판매진행 리스팅이 2개 이상 매칭 = 이미 마켓 중복
  → 재연결·신규등록 모두 부적합이므로 blocked 로 반환해 잡에서 제외
  (신규등록하면 3개째가 생긴다)

searchStockList 는 판매중 전량의 부분집합(lottehome_ghost_reconciler 참조)이라
"덤프에 없음"은 미등록의 증거가 아니다 — 덤프에 실존하는 리스팅만 재연결하고,
없는 상품은 기존과 동일하게 신규등록으로 진행한다(best-effort 예방).

LOTTEHOME_PRETRANSMIT_RECONNECT=0 으로 비활성화(기본 ON).
가드 실패는 fail-open — 전송 자체를 막지 않는다(기존 동작 유지).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from sqlalchemy import bindparam, text

logger = logging.getLogger("backend.lottehome.pretransmit_reconnect")

# backfill-goodsno 와 동일한 매칭키: 상품명 끝 5자리 이상 숫자토큰
_TOKEN_RE = re.compile(r"(\d{5,})\s*$")

# 한 잡에서 재연결 시도할 최대 상품 수 — 폭주 방지 상한
MAX_RECONNECT_PER_JOB = 5000


def _enabled() -> bool:
    return os.environ.get(
        "LOTTEHOME_PRETRANSMIT_RECONNECT", "1"
    ).strip().lower() not in ("0", "false", "no", "off")


def match_ghost_listings(
    unmapped: list[tuple[str, str]],
    dump: dict[str, tuple[str, str]],
    db_gnos: set[str],
) -> tuple[dict[str, str], set[str]]:
    """매핑 없는 상품 ↔ 판매진행 유령 리스팅 매칭 (순수 함수).

    Args:
        unmapped: (product_id, site_product_id) — 이 계정 매핑이 없는 전송 대상
        dump: goods_no -> (sale_stat_cd, goods_nm) — searchStockList 덤프
        db_gnos: 이 계정에 이미 매핑된 goods_no 집합 (유령 판정 보호셋)

    Returns:
        (reconnect: product_id -> goods_no, blocked: {product_id})
        blocked = 판매진행 리스팅 2개 이상 매칭(마켓 중복) 또는 같은
        site_product_id 상품이 2개 이상(모호) — 이번 전송에서 제외할 상품.
    """
    token_to_gnos: dict[str, list[str]] = {}
    for g, (stat, name) in dump.items():
        if stat != "10" or g in db_gnos:
            continue
        m = _TOKEN_RE.search(name)
        if m:
            token_to_gnos.setdefault(m.group(1), []).append(g)

    spid_to_pids: dict[str, list[str]] = {}
    for pid, spid in unmapped:
        if spid:
            spid_to_pids.setdefault(spid, []).append(pid)

    reconnect: dict[str, str] = {}
    blocked: set[str] = set()
    for spid, pids in spid_to_pids.items():
        gnos = token_to_gnos.get(spid)
        if not gnos:
            continue  # 덤프에 유령 없음 → 기존대로 신규등록 진행
        if len(pids) > 1:
            # 같은 원상품번호를 가진 상품이 여러 개 — 오연결 위험, 모두 제외
            blocked.update(pids)
            continue
        if len(gnos) > 1:
            # 마켓에 이미 판매진행 리스팅 2개+ — 자동 처리 부적합, 제외
            blocked.add(pids[0])
            continue
        reconnect[pids[0]] = gnos[0]
    return reconnect, blocked


async def reconnect_before_transmit(
    product_ids: list[str], target_account_ids: list[str]
) -> dict[str, Any]:
    """전송잡 시작 전 롯데홈 유령 재연결. 항상 dict 반환(fail-open).

    Returns: {accounts, checked, reconnected, blocked: [product_id...]}
    """
    result: dict[str, Any] = {
        "accounts": 0,
        "checked": 0,
        "reconnected": 0,
        "blocked": [],
    }
    if not _enabled() or not product_ids or not target_account_ids:
        return result
    try:
        return await _run(list(product_ids), list(target_account_ids), result)
    except Exception as e:
        logger.warning(f"[롯데홈 재연결가드] 실패 — 기존 동작으로 진행(fail-open): {e}")
        return result


async def _run(
    product_ids: list[str],
    target_account_ids: list[str],
    result: dict[str, Any],
) -> dict[str, Any]:
    from backend.db.orm import get_write_session
    from backend.domain.samba.proxy.lottehome_ghost_reconciler import (
        _fetch_db_mapping,
        _get_client_for,
        _stream_stocklist_names,
    )

    async with get_write_session() as session:
        acc_rows = (
            await session.execute(
                text(
                    "SELECT id, tenant_id FROM samba_market_account "
                    "WHERE id IN :aids "
                    "AND market_type = 'lottehome' AND is_active = true"
                ).bindparams(bindparam("aids", expanding=True)),
                {"aids": target_account_ids},
            )
        ).all()
    if not acc_rows:
        return result
    result["accounts"] = len(acc_rows)

    blocked_all: set[str] = set()
    for acc_id, tenant_id in acc_rows:
        acc_id = str(acc_id)
        # 이 계정 매핑이 없는 전송 대상 상품 (site_product_id 없으면 매칭 불가)
        unmapped: list[tuple[str, str]] = []
        async with get_write_session() as session:
            for i in range(0, len(product_ids), 1000):
                chunk = product_ids[i : i + 1000]
                rows = (
                    await session.execute(
                        text(
                            # 여기의 COALESCE 는 의도대로 동작한다 — jsonb 'null'
                            # 이나 (과거 오염으로 생긴) 배열이면 jsonb_exists 가
                            # false 를 돌려주므로 "매핑 없음"으로 분류되고, 아래
                            # UPDATE 의 jsonb_typeof 가드가 '{}' 로 정규화하면서
                            # 오염 값까지 함께 복구된다.
                            "SELECT id, site_product_id "
                            "FROM samba_collected_product "
                            "WHERE id IN :pids "
                            "AND NOT jsonb_exists("
                            "COALESCE(market_product_nos, '{}'::jsonb), :aid)"
                        ).bindparams(bindparam("pids", expanding=True)),
                        {"pids": chunk, "aid": acc_id},
                    )
                ).all()
                unmapped.extend((str(r[0]), str(r[1] or "").strip()) for r in rows)
        unmapped = [(p, s) for p, s in unmapped if s][:MAX_RECONNECT_PER_JOB]
        if not unmapped:
            continue
        result["checked"] += len(unmapped)

        client = await _get_client_for(tenant_id)
        if client is None:
            logger.warning(f"[롯데홈 재연결가드] {acc_id}: credentials 없음 — 스킵")
            continue
        dump = await _stream_stocklist_names(client)
        db_gnos, _ = await _fetch_db_mapping(acc_id)
        reconnect, blocked = match_ghost_listings(unmapped, dump, db_gnos)
        blocked_all.update(blocked)

        applied = 0
        if reconnect:
            async with get_write_session() as session:
                for pid, gno in reconnect.items():
                    # WHERE 재확인 — 동시 잡/backfill 과의 race 에서 이중 기록 방지
                    r = await session.execute(
                        text(
                            "UPDATE samba_collected_product SET "
                            # COALESCE 는 SQL NULL 만 거른다 — 컬럼에 jsonb 'null' 이
                            # 들어있으면 그대로 통과하고 'null' || {obj} 가
                            # [null, {...}] 배열로 변해 dict 가정 코드가 전부 깨진다.
                            # 실측(2026-07-23 프로덕션): object 101,098 / SQL NULL
                            # 31,647 / jsonb 'null' 22,769 — 이 가드의 대상인
                            # "매핑 없는 상품"이 바로 'null' 군이라 정면으로 밟는다.
                            # (같은 사고 선례: order.py 배열 오염 87건, b928641e)
                            "market_product_nos = "
                            "  (CASE WHEN jsonb_typeof(market_product_nos) = 'object' "
                            "        THEN market_product_nos ELSE '{}'::jsonb END) "
                            "  || jsonb_build_object("
                            "    CAST(:aid AS text), CAST(:gno AS text)), "
                            # registered_accounts 도 같은 함정 — jsonb 'null' 이
                            # 24,604건 있고 'null' || "acc" 는 [null, "acc"] 가 된다.
                            # 게다가 이미 null 원소가 섞인 행이 539건 있어서 단순히
                            # array 여부만 봐서는 그 null 이 그대로 남는다.
                            # → array 면 문자열 원소만 남겨 재구성하고(기존 오염 청소),
                            #   그 외(jsonb 'null' / SQL NULL)는 '[]' 에서 시작한다.
                            "registered_accounts = ("
                            "  CASE WHEN jsonb_typeof(registered_accounts) = 'array' "
                            "    THEN COALESCE(("
                            "      SELECT jsonb_agg(e) "
                            "      FROM jsonb_array_elements(registered_accounts) e "
                            "      WHERE jsonb_typeof(e) = 'string'), '[]'::jsonb) "
                            "    ELSE '[]'::jsonb END"
                            ") || ("
                            "  CASE WHEN COALESCE(registered_accounts, '[]'::jsonb) "
                            "         @> to_jsonb(CAST(:aid AS text)) "
                            "    THEN '[]'::jsonb "
                            "    ELSE to_jsonb(ARRAY[CAST(:aid AS text)]) END"
                            "), "
                            "status = 'registered' "
                            "WHERE id = :pid "
                            "AND NOT jsonb_exists("
                            "COALESCE(market_product_nos, '{}'::jsonb), :aid)"
                        ),
                        {"aid": acc_id, "gno": gno, "pid": pid},
                    )
                    applied += r.rowcount or 0
                    if applied and applied % 200 == 0:
                        await session.commit()
                await session.commit()
        result["reconnected"] += applied
        if applied or blocked:
            logger.info(
                f"[롯데홈 재연결가드] {acc_id}: 재연결 {applied}건, "
                f"중복의심 제외 {len(blocked)}건 "
                f"(검사 {len(unmapped)}건, 덤프 {len(dump)}건)"
            )

    result["blocked"] = sorted(blocked_all)
    if result["reconnected"] or result["blocked"]:
        await _log_event(result)
    return result


async def _log_event(result: dict[str, Any]) -> None:
    """monitor_event 기록 — best-effort, 실패해도 가드 동작에 영향 없음."""
    try:
        from backend.db.orm import get_write_session
        from backend.domain.samba.warroom.model import SambaMonitorEvent

        async with get_write_session() as session:
            session.add(
                SambaMonitorEvent(
                    event_type="lottehome_pretransmit_reconnect",
                    severity="warning" if result["blocked"] else "info",
                    market_type="lottehome",
                    summary=(
                        f"롯데홈 전송 전 유령 재연결 {result['reconnected']}건"
                        + (
                            f", 중복 리스팅 의심 제외 {len(result['blocked'])}건"
                            if result["blocked"]
                            else ""
                        )
                    ),
                    detail=result,
                )
            )
            await session.commit()
    except Exception as e:
        logger.debug(f"[롯데홈 재연결가드] monitor_event 기록 스킵: {e}")
