"""크림 갱신·리스톡 백엔드 오토튠 이식 — 섀도모드 [Phase 2, 2026-07-21].

집PC 로컬 루프(_kream_unified_loop.ps1)가 하던 크림 입찰갱신/리스톡을 백엔드로
단계적 이식. 프로덕션 오토튠 코어(collector_autotune.py)는 절대 안 건드리고 이 격리
모듈에서만 동작. **쓰기/POST/DB수정 전혀 없음 — target 계산 후 로그만.**

Phase 1: 백엔드↔크림 read 경로 확립(인증→live asks 조회).
Phase 2 (현재): 가격정책(base/min_price/domestic_cap)+PSA 옵션원가 매핑 포팅 →
  각 live ask 의 target 계산 → 현재가 대비 인상/인하/유지 분류 로그. 로컬 루프 결과 대조용.
Phase 3: 로컬 루프 실제행동과 대조검증(가격/랭크 일치율).
Phase 4: 검증 후 실제 실행 전환.

활성화: 환경변수 KREAM_SHADOW=1 일 때만 lifecycle 이 주기 호출(기본 off).
"""

import asyncio
import json
import logging
import math
import os
import re

import httpx
from sqlalchemy import text as _text

from backend.db.orm import get_read_session

logger = logging.getLogger(__name__)

KREAM_OPENAPI_BASE = "https://partner-openapi.kream.co.kr/openapi"
_PER_PAGE = 50  # 공식 스펙 상한(초과 시 조용히 0건)
_COOLDOWN_KEY = "kream_nocomp_cooldown"  # samba_settings 키 — {"pid|opt": epoch}
_COOLDOWN_TTL = 86400  # 24h — 무경쟁 인상 후 밀린 (상품,옵션) 재인상 금지
# [Phase4c] 실제 PATCH 실행 스위치 — 기본 하드오프(0). 로컬 루프 정지 후에만 1로 켠다(전환).
_EXECUTE = os.environ.get("KREAM_SHADOW_EXECUTE") == "1"
# 박스(해외배송) 갱신/삭제 실행 게이트 — 카드(_EXECUTE)와 별도. 섀도 검증 후 KREAM_EXEC_BOX=1.
_EXEC_BOX = os.environ.get("KREAM_EXEC_BOX") == "1"
# 신발(mm) 갱신/삭제 실행 게이트 — 섀도 검증 후 KREAM_EXEC_SHOE=1. 등록은 하지 않음.
_EXEC_SHOE = os.environ.get("KREAM_EXEC_SHOE") == "1"
_ANOMALY_FLOOR = 0.7  # target 이 시장최저의 70% 미만이면 이상(헐값) — 실행 차단
_DROP_CAP = 0.20  # 한 사이클 하향 폭 상한 = 현재가의 20%
# 슬랙 알림 — 로컬 봇(_kream_ask_adjust._send_slack)이 사이클마다 보내던 것 이식.
# 웹훅 URL은 비밀이라 local.env(KREAM_SLACK_WEBHOOK)로만 주입(리포지토리 비커밋).
_SLACK_WEBHOOK = os.environ.get("KREAM_SLACK_WEBHOOK", "")


async def _send_slack(msg: str) -> None:
    """사이클 요약 슬랙 발송. 실패해도 무시(알림 유실만, 입찰 동작 무관)."""
    if not _SLACK_WEBHOOK.startswith("https://hooks.slack.com/"):
        return
    try:
        async with httpx.AsyncClient(timeout=10) as cli:
            await cli.post(_SLACK_WEBHOOK, json={"text": msg})
    except Exception as exc:
        logger.warning("[크림통합] 슬랙 발송 실패(무시): %s", exc)


# 매수추천/원가오염 감시 상태 — {kid: {"h": 고점엔, "a": 매수알림함, "sa": 오염알림함}}
_SET_WATCH = "kream_snkr_watch"


def _rank_summary(asks: list) -> tuple[int, int, int, int]:
    """(상품,옵션) 그룹별 1순위/비1순위 집계 — 로컬 봇과 동일 기준.
    '진짜 1위' = 해외 최저(lowest_overseas, 내 입찰 포함)이면서 국내배송 최저까지 이긴 경우.
    해외만 1위고 국내가 더 싸면 구매자는 국내를 사므로 무의미한 1등 → 1순위서 제외.
    공식 API는 live_rank 가 항상 null 이라 price<=lowest 로 유도(로컬 _derive_rank1_official 동일).
    rank 없는 입찰도 반드시 비1순위로 집계해 전 입찰이 어느 한쪽에 들어가게 한다."""
    groups: dict = {}
    nocomp: dict = {}  # 무경쟁 후보 — rank1 이면서 국내배송 경쟁 자체가 없는 그룹
    for a in asks:
        k = (str(a.get("product_id") or ""), str(a.get("option") or ""))
        our = int(a.get("price") or 0)
        ov = int(a.get("lowest_overseas_price") or 0)
        dom = int(a.get("lowest_normal_price") or 0)
        rank1 = ov > 0 and 0 < our <= ov
        real1 = rank1 and (dom <= 0 or our <= dom)
        # 그룹당 real1 이 하나라도 있으면 1순위로 승격(중복입찰 대비)
        if k not in groups or (real1 and not groups[k]):
            groups[k] = real1
        if rank1 and dom <= 0:
            nocomp[k] = True
    total = len(groups)
    r1 = sum(1 for v in groups.values() if v)
    return r1, total - r1, total, len(nocomp)


async def _unfulfilled_count() -> int:
    """미이행(판매됐으나 소싱 전) 크림 주문 건수 — '소싱 필요' 알림용."""
    try:
        async with get_read_session() as s:
            r = await s.execute(
                _text(
                    "SELECT count(*) FROM samba_order "
                    "WHERE order_number LIKE 'A-LI%' "
                    "AND COALESCE(sourcing_order_number,'')='' "
                    "AND COALESCE(product_id,'')<>'' "
                    "AND status NOT IN ('cancelled','cancel_requested',"
                    "'cancel_completed','cancel_release')"
                )
            )
            return int(r.scalar_one() or 0)
    except Exception as exc:
        logger.warning("[크림통합] 미이행 조회 실패(무시): %s", exc)
        return 0


async def _orphan_report(asks: list, kid_to_snkr: dict, h: dict) -> str:
    """방치입찰(매칭 없는 live ask) — 갱신이 가격조정을 못 해 체결 시 손실위험.
    로컬 봇과 동일: 30건 이하면 자동삭제, 초과면 오탐 우려로 알림만(수동 확인)."""

    # 관리 대상(PSA 카드 / 해외배송 박스)만 판정 — 신발(mm 사이즈)은 오니츠카라
    # 스니덩크 매칭맵에 없는 게 정상. 이를 방치로 오판하면 정상 입찰이 삭제된다.
    def _managed(opt: str) -> bool:
        o = str(opt or "").upper()
        return o.startswith("PSA") or "해외배송" in str(opt or "")

    orphans = [
        a
        for a in asks
        if _managed(a.get("option"))
        and str(a.get("product_id") or "") not in kid_to_snkr
    ]
    if not orphans:
        return ""
    kids = {str(a.get("product_id")) for a in orphans}
    total = sum(int(a.get("price") or 0) for a in orphans)
    msg = (
        f"⚠️ 방치입찰(매칭없음) {len(orphans):,}건 / 상품 {len(kids):,}개 "
        f"/ 노출 {total:,}원\n"
    )
    for a in sorted(orphans, key=lambda x: -int(x.get("price") or 0))[:10]:
        _nm = str(a.get("product_name_kr") or a.get("product_name") or "")[:22]
        msg += (
            f"🔸 크림{a.get('product_id')} {a.get('option')} "
            f"{int(a.get('price') or 0):,}원 {_nm}\n"
        )
    if len(orphans) > 10:
        msg += f"외 {len(orphans) - 10:,}건\n"
    if len(orphans) > 30:
        msg += "※ 30건 초과 — 오탐 가능성으로 자동삭제 보류(수동 확인 필요)\n"
    elif _EXECUTE:
        ok = fail = 0
        async with httpx.AsyncClient(timeout=25) as cli:
            for a in orphans:
                if a.get("id") and await _exec_delete_ask(cli, h, a.get("id")):
                    ok += 1
                else:
                    fail += 1
                await asyncio.sleep(0.1)
        msg += f"🧹 자동삭제 {ok:,}건" + (f" / 실패 {fail:,}건" if fail else "") + "\n"
    msg += "※ 가격 무관리 — 매칭 연결 또는 입찰취소 필요\n"
    return msg


async def _buy_watch(snapshot: list) -> str:
    """매수추천 — 스니덩 PSA10 고점대비 30%↓ + 거래10건↑ + 재고有. 1회 알림, 회복 시 재무장.
    원가오염 의심(등급역전 / 단일리스팅 급락)도 함께. 상태는 DB(kream_snkr_watch)에 유지."""
    prev = await _load_setting_map(_SET_WATCH)
    drops: list = []
    suspects: list = []
    new_state: dict = {}
    for kid, sid, p10, s10, p9, s9 in snapshot:
        if p10 <= 0:
            continue
        st = prev.get(str(kid)) or {}
        if not isinstance(st, dict):
            st = {"h": st}
        high = int(st.get("h") or 0) or p10
        alerted = bool(st.get("a"))
        if p10 > high:  # 신고점 → 기준 갱신 + 재무장
            high, alerted = p10, False
        if p10 > high * 0.7:  # 고점 30% 이내 회복 → 재무장
            alerted = False
        traded10 = _g_trade_counts.get(str(kid), 0) >= 10
        if p10 <= high * 0.7 and not alerted and traded10 and s10 > 0:
            drops.append((kid, sid, high, p10, s10))
            alerted = True
        sus = None
        if p9 > 0 and p10 < p9 and s10 <= 2 and s9 >= 3:
            sus = f"등급역전 PSA10 {p10:,}엔 < PSA9 {p9:,}엔 (PSA10재고 {s10:,})"
        elif s10 <= 1 and p10 <= high * 0.5:
            sus = f"단일리스팅 급락 고점 {high:,}엔→{p10:,}엔 재고{s10:,}"
        sus_alerted = bool(st.get("sa"))
        if sus and not sus_alerted:
            suspects.append((kid, sid, sus))
            sus_alerted = True
        elif not sus:
            sus_alerted = False  # 정상 회복 시 재무장
        new_state[str(kid)] = {"h": high, "a": alerted, "sa": sus_alerted}
    await _save_setting_map(_SET_WATCH, {**prev, **new_state})
    # 로컬 포맷 그대로 — 급락 0건이어도 '매수추천 없음' 줄을 항상 낸다(구분선 14칸).
    if not drops:
        out = "💤 매수추천 없음 (스니덩 PSA10 고점대비 30%↓ 급락 0건)\n━━━━━━━━━━━━━━\n"
    else:
        out = f"🚨💰 매수추천! 스니덩 PSA10 고점대비 30%↓ {len(drops):,}건 💰🚨\n━━━━━━━━━━━━━━"
        for kid, sid, hi, cu, stk in drops[:15]:
            pct = int((1 - cu / hi) * 100)
            out += (
                f"\n🟢 고점¥{hi:,}→¥{cu:,} (-{pct}%, 재고{stk})"
                f"\n   크림 https://kream.co.kr/products/{kid}"
                f"  스니덩 https://snkrdunk.com/apparels/{sid}"
            )
        if len(drops) > 15:
            out += f"\n외 {len(drops) - 15:,}건"
        out += "\n━━━━━━━━━━━━━━\n"
    if suspects:
        out += f"🧪 원가오염 의심 {len(suspects):,}건 (눈으로 확인 필요)\n"
        for kid, sid, s in suspects[:8]:
            out += f"• 크림{kid}: {s}\n"
    return out


# 가격정책 — 로컬 _kream_ask_adjust.py POLICY 포팅(동일 기본값). 추후 마진설정 API 로 교체 가능.
POLICY = {
    "min_margin_amount": 9000,
    "competitive_margin_rate": 13,
    "no_competition_margin_rate": 31,
    "shipping_fee_card": 300,  # 스니덩크 배송비(카드) — 엔화
    "shipping_fee_box": 900,  # 스니덩크 배송비(박스) — 엔화
    "forwarding_fee": 8000,  # 배대지비용 — 원
    "box_pack_margin_rate": 0,  # 박스/카드팩(PSA제외 실링) 원가 추가마진율(%) — 정책설정
    "non_card_margin_rate": 5,  # 나머지(신발/의류) 원가 추가마진율(%) — 정책설정, 하드코딩 금지
    # 입찰 최고 원가(엔) — 이 값 초과 상품은 갱신·리스톡 모두 제외. 로컬 봇의 25만엔 원칙.
    # 초고가 카드(수백만엔)에 입찰이 걸리면 체결 시 그 값으로 소싱해야 해 치명적.
    "max_cost_jpy": 250000,
    # 조정 데드밴드(%) — 목표가와 현재가 차이가 이 비율 미만이면 조정 생략.
    # 실시간 원가/시세의 미세변동이 매 사이클 수백 건의 헛조정으로 번지는 것 차단.
    # 단 '마진 하한 미달(현재가 < 최소가)' 은 손실 방지라 데드밴드와 무관하게 항상 조정.
    "adjust_deadband_pct": 1.5,
}


async def _load_policy() -> None:
    """정책관리 KREAM 탭 설정을 DB(SambaPolicy.market_policies)서 읽어 POLICY 갱신.
    로컬 루프(_kream_ask_adjust)가 라이브 정책을 쓰므로 섀도도 동일 소스여야 target 일치.
    실패해도 기본값 유지."""
    try:
        from sqlmodel import select

        from backend.domain.samba.policy.model import SambaPolicy

        async with get_read_session() as s:
            rows = (await s.execute(select(SambaPolicy.market_policies))).all()
        for (mp,) in rows:
            if isinstance(mp, dict) and isinstance(mp.get("KREAM"), dict):
                k = mp["KREAM"]
                POLICY.update(
                    {
                        "min_margin_amount": k.get(
                            "kreamMinMarginAmount", POLICY["min_margin_amount"]
                        ),
                        "competitive_margin_rate": k.get(
                            "kreamCompetitiveMarginRate",
                            POLICY["competitive_margin_rate"],
                        ),
                        "no_competition_margin_rate": k.get(
                            "kreamNoCompetitionMarginRate",
                            POLICY["no_competition_margin_rate"],
                        ),
                        "shipping_fee_card": k.get(
                            "kreamShippingFeeCard", POLICY["shipping_fee_card"]
                        ),
                        "shipping_fee_box": k.get(
                            "kreamShippingFeeBox", POLICY["shipping_fee_box"]
                        ),
                        "forwarding_fee": k.get(
                            "kreamForwardingFee", POLICY["forwarding_fee"]
                        ),
                        "box_pack_margin_rate": k.get(
                            "kreamBoxPackMarginRate", POLICY["box_pack_margin_rate"]
                        ),
                        "non_card_margin_rate": k.get(
                            "kreamNonCardMarginRate", POLICY["non_card_margin_rate"]
                        ),
                        "max_cost_jpy": k.get(
                            "kreamMaxCostJpy", POLICY["max_cost_jpy"]
                        ),
                        "adjust_deadband_pct": k.get(
                            "kreamAdjustDeadbandPct", POLICY["adjust_deadband_pct"]
                        ),
                    }
                )
                return
    except Exception as exc:
        logger.warning("[크림섀도] 마진정책 조회 실패, 기본값 유지: %s", exc)


async def _load_cooldown() -> set:
    """무경쟁 인상 쿨다운 — samba_settings 'kream_nocomp_cooldown'({pid|opt: epoch}) 24h 내만."""
    try:
        import time  # noqa: F811 (로컬 import — 모듈레벨 import 가 포맷터에 제거되는 경합 회피)

        from sqlmodel import select

        from backend.domain.samba.forbidden.model import SambaSettings

        async with get_read_session() as s:
            val = (
                await s.execute(
                    select(SambaSettings.value).where(
                        SambaSettings.key == _COOLDOWN_KEY
                    )
                )
            ).scalar_one_or_none()
        data = val if isinstance(val, dict) else {}
        now = time.time()
        return {
            tuple(k.split("|", 1))
            for k, v in data.items()
            if now - float(v) < _COOLDOWN_TTL
        }
    except Exception as exc:
        logger.warning("[크림섀도] 쿨다운 조회 실패: %s", exc)
        return set()


async def record_nocomp_cooldown(pid: str, opt: str) -> None:
    """무경쟁 인상 후 밀린 (상품,옵션) 쿨다운 기록 — Phase4c 실행부에서 호출."""
    try:
        import time  # noqa: F811

        from sqlmodel import select

        from backend.db.orm import get_write_session
        from backend.domain.samba.forbidden.model import SambaSettings

        async with get_write_session() as s:
            row = (
                (
                    await s.execute(
                        select(SambaSettings).where(SambaSettings.key == _COOLDOWN_KEY)
                    )
                )
                .scalars()
                .first()
            )
            data = dict(row.value) if row and isinstance(row.value, dict) else {}
            now = time.time()
            data = {k: v for k, v in data.items() if now - float(v) < _COOLDOWN_TTL}
            data[f"{pid}|{opt}"] = now
            if row:
                row.value = data
                s.add(row)
            else:
                s.add(SambaSettings(key=_COOLDOWN_KEY, value=data))
            await s.commit()
    except Exception as exc:
        logger.warning("[크림섀도] 쿨다운 기록 실패: %s", exc)


# 크림 전용 프로세스(PROCESS_ROLE=kream)는 api 프로세스와 별도 메모리라
# refresher._refresh_log_buffer(api-local)에 직접 append 못 함. 대신 DB 테이블
# kream_refresh_log 에 남기고, api 쪽 테일러(lifecycle `_kream_log_tailer`)가 폴링해
# refresher.ingest_kream_log 로 UI 버퍼에 주입한다. 이 프로세스에선 사이클 단위로
# _pending_logs 에 모았다가 사이클 끝에 _flush_logs_to_db()로 일괄 INSERT(왕복 최소화).
_LOG_TABLE = "kream_refresh_log"
_LOG_TRIM_KEEP = 1500  # 링버퍼 성격 — 최근 N행만 유지
_pending_logs: list[dict] = []

# [Step 3] 통합 전수순회 배치 로테이션 offset(사이클 간 유지, 재시작 시 0). 카탈로그 순차 커버.
_unified_offset = 0
# 크림 오토튠 활성사이클 표시용 — DB(samba_settings 'kream_cycle_status')로 api 엔드포인트에 브리지.
_kream_cycle_count = 0
_kream_started_at = None


async def _save_kream_cycle_status(
    idx: int, total: int, price_cnt: int, del_cnt: int
) -> None:
    """크림 사이클 진행상태를 DB 기록 → api /autotune/active-cycles 가 읽어 SNKRDUNK 활성 표시."""
    global _kream_cycle_count, _kream_started_at
    from datetime import datetime, timezone

    _kream_cycle_count += 1
    now_iso = datetime.now(timezone.utc).isoformat()
    if _kream_started_at is None:
        _kream_started_at = now_iso
    try:
        from backend.db.orm import get_write_session

        payload = {
            "idx": int(idx),
            "total": int(total),
            "price_count": int(price_cnt),
            "delete_count": int(del_cnt),
            "cycle_count": _kream_cycle_count,
            "started_at": _kream_started_at,
            "updated_at": now_iso,
            "execute": _EXECUTE,
        }
        async with get_write_session() as s:
            await s.execute(
                _text(
                    "INSERT INTO samba_settings (key, value, updated_at) "
                    "VALUES ('kream_cycle_status', CAST(:v AS json), NOW()) "
                    "ON CONFLICT (key) DO UPDATE SET value = CAST(:v AS json), updated_at = NOW()"
                ),
                {"v": json.dumps(payload, ensure_ascii=False)},
            )
            await s.commit()
    except Exception as exc:
        logger.warning("[크림통합] 사이클상태 저장 실패: %s", exc)


def _emit_autotune_log(
    site: str, product_id: str, msg: str, level: str = "info"
) -> None:
    """크림 로그 1줄을 사이클 버퍼에 적재(포맷=오토튠 UI와 동일 `[HH:MM:SS] [SITE] ...`).
    실제 DB 기록은 사이클 끝 _flush_logs_to_db() 가 일괄 처리."""
    try:
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        ts = (now + timedelta(hours=9)).strftime("%H:%M:%S")
        _pending_logs.append(
            {
                "site": site,
                "product_id": str(product_id or ""),
                "msg": f"[{ts}] [{site}] {msg}",
                "level": level,
                "device_id": "",  # 빈 device_id = 글로벌 → 어느 PC 필터에서도 노출
            }
        )
    except Exception:
        pass


async def _flush_logs_to_db() -> None:
    """사이클 버퍼(_pending_logs)를 kream_refresh_log 에 일괄 INSERT + 오래된 행 트림.
    실패해도 무시(로그 유실만, 입찰 동작 무관)."""
    if not _pending_logs:
        return
    rows = _pending_logs[:]
    _pending_logs.clear()
    try:
        from backend.db.orm import get_write_session

        async with get_write_session() as s:
            await s.execute(
                _text(
                    f"INSERT INTO {_LOG_TABLE} (site, product_id, msg, level, device_id) "
                    "VALUES (:site, :product_id, :msg, :level, :device_id)"
                ),
                rows,
            )
            await s.execute(
                _text(
                    f"DELETE FROM {_LOG_TABLE} WHERE id < "
                    f"(SELECT COALESCE(MAX(id), 0) - {int(_LOG_TRIM_KEEP)} FROM {_LOG_TABLE})"
                )
            )
            await (
                s.commit()
            )  # get_write_session은 auto-commit 안 함 — 명시 커밋 필수(안 하면 롤백)
    except Exception as exc:
        logger.warning("[크림섀도] 로그 DB flush 실패(무시): %s", exc)


async def tail_kream_logs(last_id: int) -> int:
    """[api 프로세스 전용] kream_refresh_log 신규 행(id > last_id)을 읽어 refresher
    링버퍼에 주입 → 오토튠 UI 노출. 새 last_id 반환(없으면 그대로). 실패 시 last_id 유지."""
    try:
        from backend.domain.samba.collector import refresher as _ref

        async with get_read_session() as s:
            rows = (
                await s.execute(
                    _text(
                        f"SELECT id, site, product_id, msg, level, device_id "
                        f"FROM {_LOG_TABLE} WHERE id > :last ORDER BY id LIMIT 500"
                    ),
                    {"last": int(last_id)},
                )
            ).all()
        new_last = last_id
        for _id, site, product_id, msg, level, device_id in rows:
            _ref.ingest_kream_log(
                site or "KREAM",
                product_id or "",
                msg or "",
                level or "info",
                device_id or "",
            )
            new_last = max(new_last, int(_id))
        return new_last
    except Exception as exc:
        logger.warning("[크림섀도] 로그 tail 실패(무시): %s", exc)
        return last_id


async def kream_log_max_id() -> int:
    """[api 프로세스 전용] 테일러 시작점 — 현재 최대 id(과거 로그 replay 방지)."""
    try:
        async with get_read_session() as s:
            v = (
                await s.execute(_text(f"SELECT COALESCE(MAX(id), 0) FROM {_LOG_TABLE}"))
            ).scalar_one_or_none()
        return int(v or 0)
    except Exception:
        return 0


# 갱신 실패 사유 집계 — 사이클마다 초기화, 슬랙/로그에 breakdown 노출(로컬 봇과 동일).
_fail_reasons: dict = {}


def _note_fail(reason: str) -> None:
    _fail_reasons[reason] = _fail_reasons.get(reason, 0) + 1


def _now_ts() -> float:
    import time  # noqa: F811

    return time.time()


# 입찰제한 보정 사이클 상한 — 대량 오조정 방지(로컬 _hb_clamp 와 동일 취지)
_hb_clamp = {"used": 0, "cap": 20}
# (kid, opt) → 마진 하한. 순위교정 시 이 아래로는 절대 안 내린다.
_floor_map: dict = {}
# 순위교정(rank>=2 → 1,000원 인하) 사이클 상한
_rank_fix = {"used": 0, "cap": 300}


async def _fetch_highest_bid(cli, h, pid: str, opt: str) -> int:
    """옵션별 최고구매입찰가 — 크림 판매입찰가는 이 값 이상이어야 등록/수정된다."""
    try:
        r = await cli.get(f"{KREAM_OPENAPI_BASE}/products/{pid}", headers=h)
        if r.status_code != 200:
            return 0
        for o in (r.json() or {}).get("options") or []:
            if str(o.get("name") or "") == opt:
                return int(o.get("highest_bid") or 0)
    except Exception:
        pass
    return 0


async def _execute_update(cli, h, ask_id, target, cur, is_nocomp, pid, opt) -> tuple:
    """실제 PATCH 실행(가격조정) — 응답 live_rank 검증 [Phase4c]. _EXECUTE=1 일 때만 호출.
    무경쟁 인상인데 rank!=1(밀림)이면 원가로 복귀 + 24h 쿨다운 기록(재스윙 방지)."""
    try:
        r = await cli.patch(
            f"{KREAM_OPENAPI_BASE}/asks/{ask_id}",
            headers=h,
            json={"price": int(target)},
        )
        if r.status_code not in (200, 201):
            # 사유 기록 — 그동안 실패 건수만 보이고 원인을 몰라 대응이 불가했다.
            _body = " ".join((r.text or "")[:120].split())
            # 입찰제한(최근 거래가 확인 필요) → 최고구매입찰가로 1회 보정 재시도.
            # 크림은 판매입찰가가 highest_bid 미만이면 거절한다(로컬 봇과 동일 대응).
            if ("거래가" in _body or "입찰제한" in _body) and _hb_clamp[
                "used"
            ] < _hb_clamp["cap"]:
                hb = await _fetch_highest_bid(cli, h, pid, opt)
                if hb > 0 and hb != int(target):
                    _hb_clamp["used"] += 1
                    hb = int(hb) // 1000 * 1000
                    r2 = await cli.patch(
                        f"{KREAM_OPENAPI_BASE}/asks/{ask_id}",
                        headers=h,
                        json={"price": int(hb)},
                    )
                    if r2.status_code in (200, 201):
                        return "ok", (r2.json() or {}).get("live_rank")
                    _note_fail(
                        f"HTTP {r2.status_code}(최고입찰가보정): "
                        + " ".join((r2.text or "")[:80].split())
                    )
                    _g_limit_cd[f"{pid}|{opt}"] = _now_ts()
                    return "fail", None
            if "거래가" in _body or "입찰제한" in _body:
                _g_limit_cd[f"{pid}|{opt}"] = _now_ts()
                # 패턴 파악용 수치 — 변동폭이 큰 건에서만 나는지 확인해야 대응 가능
                _pct = ((int(target) - int(cur)) / int(cur) * 100) if cur else 0
                logger.info(
                    "[크림통합] 입찰제한 %s %s: %s→%s (%+.1f%%)",
                    pid,
                    opt,
                    f"{int(cur):,}",
                    f"{int(target):,}",
                    _pct,
                )
            _note_fail(f"HTTP {r.status_code}: {_body}")
            return "fail", None
        rank = (r.json() or {}).get("live_rank")
        # ── 순위 교정 [2026-07-23] — 공식 API의 lowest_* 가 우리 가격만 되비추는 사례가
        # 확인돼(659534: 상대 842,000 존재하나 API 최저가는 우리 843,000) 시세 기준만으론
        # 열세를 감지할 수 없다. PATCH 응답의 live_rank 는 정확하므로 이걸로 교정한다.
        # 마진 하한 미만으론 절대 안 내림 — 하한이면 2등을 수용(동률·마진제약 케이스).
        if (
            not is_nocomp
            and rank is not None
            and int(rank) >= 2
            and _rank_fix["used"] < _rank_fix["cap"]
        ):
            _floor = int(_floor_map.get((str(pid), str(opt)), 0) or 0)
            _new = int(target) - 1000
            if _new > 0 and _floor > 0 and _new >= _floor:
                _rank_fix["used"] += 1
                r3 = await cli.patch(
                    f"{KREAM_OPENAPI_BASE}/asks/{ask_id}",
                    headers=h,
                    json={"price": _new},
                )
                if r3.status_code in (200, 201):
                    return "ok", (r3.json() or {}).get("live_rank")
        if is_nocomp and rank is not None and rank != 1:
            await cli.patch(
                f"{KREAM_OPENAPI_BASE}/asks/{ask_id}",
                headers=h,
                json={"price": int(cur)},
            )
            await record_nocomp_cooldown(pid, opt)
            return "reverted", rank
        return "ok", rank
    except Exception as exc:
        _note_fail(f"예외 {type(exc).__name__}: {str(exc)[:80]}")
        logger.warning("[크림섀도] PATCH 실패 ask=%s: %s", ask_id, exc)
        return "error", None


def calc_base(
    price_jpy: float,
    rate: float,
    is_box: bool = False,
    is_card: bool = True,
    surcharge_rate: float | None = None,
) -> float:
    """원가 base = (snkr엔 + 배송엔)×환율 + 배대지비(원).
    추가마진율(%)만큼 원가 가산 — 정책값 사용(하드코딩 금지).
      · surcharge_rate 명시: 호출부가 분류(PSA=0 / 박스·카드팩 / 신발·의류)해서 넘김
      · 미지정: PSA면 0, 비PSA는 박스/카드팩으로 간주(box_pack_margin_rate)"""
    ship_jpy = POLICY["shipping_fee_box"] if is_box else POLICY["shipping_fee_card"]
    if surcharge_rate is None:
        surcharge_rate = 0 if is_card else POLICY["box_pack_margin_rate"]
    eff_jpy = price_jpy * (1 + surcharge_rate / 100)
    return (eff_jpy + ship_jpy) * rate + POLICY["forwarding_fee"]


def calc_min_price(
    price_jpy: float,
    rate: float,
    is_box: bool = False,
    is_card: bool = True,
    surcharge_rate: float | None = None,
) -> int:
    base = calc_base(price_jpy, rate, is_box, is_card, surcharge_rate)
    margin = max(
        float(POLICY["min_margin_amount"]),
        base * POLICY["competitive_margin_rate"] / 100,
    )
    return int((base + margin + 999) // 1000 * 1000)


def domestic_cap(low_norm: int, tariff_threshold: int) -> int:
    """해외판매 상한 — 구매자 체감가(면세초과분 관세 10%)가 국내×0.9 이하. low_norm=0 → 무제한."""
    if not low_norm:
        return 10**12
    cand = low_norm * 0.9
    cap = cand if cand <= tariff_threshold else max(float(tariff_threshold), cand / 1.1)
    return int(cap // 1000 * 1000)


async def _load_kream_creds() -> tuple[str, str, str]:
    async with get_read_session() as s:
        row = (
            await s.execute(
                _text(
                    "SELECT api_key, api_secret, additional_fields::jsonb AS af "
                    "FROM samba_market_account WHERE market_type='kream' LIMIT 1"
                )
            )
        ).first()
    if not row:
        return "", "", ""
    af = row[2] or {}
    if isinstance(af, str):
        try:
            af = json.loads(af)
        except Exception:
            af = {}
    return (
        str(af.get("apiService") or ""),
        str(row[0] or af.get("apiKey") or ""),
        str(row[1] or af.get("apiSecret") or ""),
    )


def _headers(service: str, key: str, secret: str) -> dict:
    return {
        "x-kream-partner-api-service": service,
        "x-kream-partner-api-key": key,
        "x-kream-partner-api-secret": secret,
        "Accept": "application/json",
    }


async def _fetch_live_asks(h: dict) -> list[dict]:
    """내 live 입찰 전량(공식 OpenAPI, 페이징). 읽기 전용."""
    out: list[dict] = []
    page = 1
    async with httpx.AsyncClient(timeout=25) as cli:
        while True:
            r = await cli.get(
                f"{KREAM_OPENAPI_BASE}/asks",
                headers=h,
                params={"status": "live", "page": page, "per_page": _PER_PAGE},
            )
            r.raise_for_status()
            d = r.json()
            items = d.get("items") or []
            out.extend(items)
            total = int(d.get("total") or 0)
            if not items or page * _PER_PAGE >= total:
                break
            page += 1
    return out


# [Step 4] 환율 소스 = 로컬 봇(_kream_ask_adjust get_rate_cached)과 동일 frankfurter로 정렬.
# 실행 전환 시 백엔드/로컬 target 일치 보장. UA 헤더 필수(없으면 301). 마지막 성공값 인메모리 캐시로
# 순간 조회실패 시 폴백 점프 방지. (구 exchange_rate_service 경로는 rates["KRW"] 키 부재로
# 항상 폴백 9.12 반환하던 버그 — frankfurter 직조회로 대체.)
_rate_cache: dict[str, float] = {}


async def _frankfurter_rate(frm: str, to: str, fallback: float) -> float:
    pair = f"{frm}/{to}"
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as cli:
            r = await cli.get(
                f"https://api.frankfurter.app/latest?from={frm}&to={to}",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            r.raise_for_status()
            v = float((r.json().get("rates") or {}).get(to) or 0)
        if v > 0:
            _rate_cache[pair] = v
            return v
    except Exception as exc:
        logger.warning("[크림] 환율 %s 조회 실패: %s", pair, str(exc)[:60])
    return _rate_cache.get(pair, fallback)


async def _jpy_krw_rate() -> float:
    """JPY/KRW — 로컬 get_rate_cached('JPY/KRW', 9.5021) 동일 소스."""
    return await _frankfurter_rate("JPY", "KRW", 9.5021)


async def _usd_krw_rate() -> float:
    """USD/KRW — 로컬 get_rate_cached('USD/KRW', 1531.0) 동일 소스(관세 면세한도용)."""
    return await _frankfurter_rate("USD", "KRW", 1531.0)


# ── 스니덩크 실시간 원가·재고 [Step 3a] — 로컬 _kream_restock_register.fetch_psa 충실 포팅.
# 백엔드 터널IP서 직접 접근 검증됨(200 + 정상 JSON). 프록시·CDP 불필요.
_SNKR_USED_URL = "https://snkrdunk.com/v1/apparels/{id}/used"
_SNKR_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "ja-JP,ja;q=0.9",
    "Referer": "https://snkrdunk.com/",
}


async def _fetch_snkr_used(cli: httpx.AsyncClient, snkr_id: str) -> dict | None:
    """스니덩크 중고(PSA10/PSA9) 옵션별 실시간 최저가(JPY)·재고수.
    page1 실패 시 None(기존 DB값 유지 — 오판 방지). 반환:
    {"PSA 10": {"price": jpy, "stock": n}, "PSA 9": {...}}.
    displayShortConditionTitle 로 PSA10/9 분류, isDisplaySold 제외, price 최저 + 개수 집계."""
    cond_min: dict = {}
    cond_cnt: dict = {}
    page = 1
    while page <= 20:
        try:
            r = await cli.get(
                _SNKR_USED_URL.format(id=snkr_id),
                headers=_SNKR_HEADERS,
                params={
                    "perPage": 100,
                    "page": page,
                    "sizeId": 0,
                    "isSaleOnly": "true",
                },
            )
            r.raise_for_status()
            items = r.json().get("apparelUsedItems") or []
        except Exception:
            if page == 1:
                return None
            break
        if not items:
            break
        for x in items:
            if not isinstance(x, dict) or x.get("isDisplaySold"):
                continue
            cond = (x.get("displayShortConditionTitle") or "").strip()
            if re.match(r"PSA\s*10\b", cond, re.IGNORECASE):
                ckey = "PSA 10"
            elif re.match(r"PSA\s*9\b", cond, re.IGNORECASE):
                ckey = "PSA 9"
            else:
                continue
            p = x.get("price")
            if not isinstance(p, (int, float)) or p <= 0:
                continue
            p = int(p)
            if ckey not in cond_min or p < cond_min[ckey]:
                cond_min[ckey] = p
            cond_cnt[ckey] = cond_cnt.get(ckey, 0) + 1
        if len(items) < 100:
            break
        page += 1
        await asyncio.sleep(0.2)
    return {
        k: {"price": cond_min.get(k, 0), "stock": cond_cnt.get(k, 0)}
        for k in ["PSA 10", "PSA 9"]
    }


async def _fetch_snkr_box(cli: httpx.AsyncClient, snkr_id: str) -> dict:
    """봉인 박스 최저가(JPY)·재고. GET /v1/apparels/{id} → {minPrice, listingCount}.
    로컬 fetch_snkr_box_price_sync 포팅. API 실패=-1(재고0과 구분, 삭제 금지)."""
    try:
        r = await cli.get(
            f"https://snkrdunk.com/v1/apparels/{snkr_id}", headers=_SNKR_HEADERS
        )
        r.raise_for_status()
        d = r.json()
        return {
            "price": int(d.get("minPrice") or 0),
            "stock": int(d.get("listingCount") or 0),
        }
    except Exception:
        return {"price": -1, "stock": -1}


async def _fetch_snkr_pack(cli: httpx.AsyncClient, snkr_id: str) -> dict | None:
    """카드팩 팩수별 최저가(JPY) {N: 엔}. HTML 파싱(sizeNameパック + minNewListingPrice).
    로컬 fetch_snkr_pack_prices_sync 포팅. 1팩×N 곱셈 금지(팩수별 실시세)."""
    try:
        r = await cli.get(
            f"https://snkrdunk.com/apparels/{snkr_id}",
            headers={**_SNKR_HEADERS, "Accept": "text/html"},
        )
        r.raise_for_status()
        html = r.text.replace('\\"', '"')
        out: dict[int, int] = {}
        for m in re.finditer(
            r'"sizeName":"(\d+)パック"[^}]*\},"minNewListingPrice":(\d+)', html
        ):
            n, p = int(m.group(1)), int(m.group(2))
            if p > 0 and (n not in out or p < out[n]):
                out[n] = p
        return out or None
    except Exception:
        return None


async def _load_snkr_option_prices(pids: set[str]) -> tuple[dict, dict]:
    """(원가맵, 지정가맵) — (kream_pid, 옵션명) → 스니덩크 원가(JPY) / 지정가(fixedPrice, 원).
    지정가(fixedEnabled)는 원가무관 사용자 확정가 → 실행 시 그 값으로 고정."""
    if not pids:
        return {}, {}
    out: dict = {}
    fixed: dict = {}
    async with get_read_session() as s:
        rows = (
            await s.execute(
                _text(
                    "SELECT resell_matches->'kream'->>'product_id' AS kid, options::text AS opts "
                    "FROM samba_collected_product WHERE source_site='SNKRDUNK' "
                    "AND resell_matches->'kream'->>'product_id' = ANY(:pids)"
                ),
                {"pids": list(pids)},
            )
        ).all()
    for kid, opts_txt in rows:
        if not opts_txt:
            continue
        try:
            opts = json.loads(opts_txt)
        except Exception:
            continue
        for o in opts:
            if not (isinstance(o, dict) and o.get("name")):
                continue
            k = (str(kid), str(o["name"]))
            if (o.get("price") or 0) > 0:
                out[k] = int(o["price"])
            if o.get("fixedEnabled") and o.get("fixedPrice"):
                fixed[k] = int(o["fixedPrice"])
    return out, fixed


async def run_kream_shadow_once() -> dict:
    """Phase 2 섀도 1회 — live 입찰별 target 계산, 현재가 대비 분류 로그. 쓰기·POST 없음."""
    service, key, secret = await _load_kream_creds()
    if not (service and key and secret):
        logger.warning("[크림섀도] 인증정보 없음 — 스킵")
        return {"ok": False, "reason": "no_creds"}

    h = _headers(service, key, secret)
    try:
        asks = await _fetch_live_asks(h)
    except Exception as exc:
        logger.warning("[크림섀도] live 입찰 조회 실패: %s", exc)
        return {"ok": False, "reason": f"fetch_error: {exc}"}

    await _load_policy()  # 라이브 마진정책 반영(로컬 루프와 동일 소스) — target 일치용
    cooldown = await _load_cooldown()
    pids = {str(a.get("product_id")) for a in asks if a.get("product_id")}
    price_map, fixed_map = await _load_snkr_option_prices(pids)
    rate = await _jpy_krw_rate()
    tariff_threshold = int(150 * await _usd_krw_rate())

    # [Phase4a] 로컬 _kream_ask_adjust 결정로직 충실 이식 — rank1 유도(price<=lowest) +
    # 5분기(마진미달인상/경쟁추종인상/무경쟁인상/과가격하향/유지) + rank1없음 추종. 로그만, PATCH 없음.
    # (쿨다운 상태저장은 Phase4b, 실제 PATCH·PATCH응답 rank검증은 Phase4c에서)
    from collections import Counter as _Counter

    acts: _Counter = _Counter()
    computed = no_cost = cd_blocked = anomaly_c = _emitted = 0
    samples: list[dict] = []
    pending_exec: list[tuple] = []  # (ask_id, target, is_nocomp, cur, pid, opt)
    _emit_autotune_log(
        "KREAM",
        "",
        f"사이클 시작 — live 입찰 {len(asks):,}건 ({'실행ON' if _EXECUTE else '섀도'})",
    )
    for a in asks:
        pid = str(a.get("product_id") or "")
        opt = str(a.get("option") or "")
        cur = int(a.get("price") or 0)
        ask_id = a.get("id")
        snkr_jpy = price_map.get((pid, opt))
        if not snkr_jpy:
            no_cost += 1
            continue
        computed += 1
        is_card = opt.upper().startswith("PSA")
        min_price = calc_min_price(snkr_jpy, rate, False, is_card)
        base = calc_base(snkr_jpy, rate, False, is_card)
        no_comp = (
            math.ceil(base * (1 + POLICY["no_competition_margin_rate"] / 100) / 1000)
            * 1000
        )
        low_over = int(a.get("lowest_overseas_price") or 0)
        low_norm = int(a.get("lowest_normal_price") or 0)
        is_ov = bool(low_over)
        market_low = (low_over if is_ov else low_norm) or low_over or low_norm
        rank1 = market_low > 0 and 0 < cur <= market_low  # _derive_rank1_official
        no_comp_eff = min(no_comp, domestic_cap(low_norm, tariff_threshold))
        band = max(3000, int(no_comp_eff * 0.03))
        # 단일 ask 기준(대다수) → rank 연속=rank1 이면 충족. 시장최저>=무경쟁가도 무경쟁 취급.
        truly_nocomp = (rank1 or market_low >= no_comp_eff) and no_comp_eff > min_price

        act, target = "유지", cur
        if rank1:
            if cur == min_price - 1000:
                act = "유지(동률)"
            elif cur < min_price:
                act, target = "마진미달인상", min_price
            elif market_low > 0 and cur < market_low - 1000:
                target = max(market_low - 1000, min_price)
                act = "경쟁추종인상" if target > cur else "유지"
            elif truly_nocomp and cur < no_comp_eff - band:
                # 무경쟁 인상 — 최근 밀림(24h 쿨다운) 이면 보류(재스윙 방지)
                if (pid, opt) in cooldown:
                    act = "무경쟁인상(쿨다운보류)"
                    cd_blocked += 1
                else:
                    act, target = "무경쟁인상", no_comp_eff
            elif truly_nocomp and cur > no_comp_eff + band:
                act, target = "과가격하향", no_comp_eff
        else:  # rank2 이하 — 경쟁 추종
            if is_ov:
                market_target = (low_over - 1000) if low_over > 0 else 0
            else:
                market_target = (low_norm - 5000) if low_norm > 0 else 0
            if market_target == 0:
                target = max(no_comp, min_price)
            elif market_target == min_price - 1000:
                target = min_price - 1000
            elif market_target <= min_price:
                target = min_price
            else:
                target = max(market_target, min_price)
            act = "no_rank1추종" if cur != target else "유지"

        # ── 안전장치 [Phase4c] ──
        fx = fixed_map.get((pid, opt))
        if fx:  # 지정가(사용자 확정가) — 원가무관 그 값으로
            target, act = fx, "지정가" if fx != cur else "유지"
        _adjusting = act not in ("유지", "유지(동률)", "무경쟁인상(쿨다운보류)")
        if _adjusting and target < cur:  # 하향 폭 20% 캡
            target = max(target, int(cur * (1 - _DROP_CAP)))
        if _adjusting and market_low > 0 and target < market_low * _ANOMALY_FLOOR:
            # 이상감지 — 시장최저 70% 미만 헐값 → 실행 차단(유지)
            act, target = "이상감지차단", cur
            anomaly_c += 1
            _adjusting = False

        acts[act] += 1
        if _adjusting and target != cur and ask_id is not None:
            pending_exec.append((ask_id, target, act == "무경쟁인상", cur, pid, opt))
        # 오토튠 실시간 로그 — 조정건만 노출. 공유버퍼(300) 홍수방지 위해 사이클당 120건 캡.
        if act not in ("유지", "유지(동률)") and _emitted < 120:
            _emitted += 1
            _pname = str(a.get("product_name_kr") or a.get("product_name") or "")[:40]
            if target != cur:
                _emit_autotune_log(
                    "KREAM",
                    pid,
                    f"{_pname} ({opt}): 가격변동 {cur:,}→{target:,} [{act}]",
                )
            else:
                _emit_autotune_log(
                    "KREAM", pid, f"{_pname} ({opt}): {act} (현재가 {cur:,} 유지)"
                )
        if act not in ("유지", "유지(동률)") and len(samples) < 10:
            samples.append(
                {"pid": pid, "opt": opt, "cur": cur, "target": target, "act": act}
            )

    # ── 실제 실행 [Phase4c] — _EXECUTE=1 일 때만. 하드오프(기본)면 계산·로그만.
    exec_ok = exec_revert = exec_fail = 0
    if _EXECUTE and pending_exec:
        import asyncio as _asyncio

        async with httpx.AsyncClient(timeout=25) as cli:
            for ask_id, target, is_nocomp, cur, pid, opt in pending_exec:
                res, _rank = await _execute_update(
                    cli, h, ask_id, target, cur, is_nocomp, pid, opt
                )
                if res == "ok":
                    exec_ok += 1
                elif res == "reverted":
                    exec_revert += 1
                else:
                    exec_fail += 1
                await _asyncio.sleep(0.1)  # rate limit 50/3s 여유

    _emit_autotune_log(
        "KREAM",
        "",
        f"사이클 완료 — 조정대상 {len(pending_exec):,}건 "
        + (
            f"/ 실행 {exec_ok:,} 복귀 {exec_revert:,} 실패 {exec_fail:,}"
            if _EXECUTE
            else "(섀도 — 미실행)"
        )
        + f" / 쿨다운보류 {cd_blocked:,} 이상차단 {anomaly_c:,}",
    )

    summary = {
        "ok": True,
        "live_asks": len(asks),
        "target_computed": computed,
        "actions": dict(acts),
        "cooldown_size": len(cooldown),
        "cooldown_blocked": cd_blocked,
        "anomaly_blocked": anomaly_c,
        "pending_exec": len(pending_exec),
        "execute_on": _EXECUTE,
        "executed": exec_ok,
        "reverted": exec_revert,
        "exec_fail": exec_fail,
        "no_snkr_cost": no_cost,
        "rate_jpy_krw": round(rate, 3),
        "samples": samples,
    }
    logger.info(
        "[크림섀도] Phase4c(%s) — 입찰%d 계산%d / 결정%s / 쿨다운%d(보류%d) 이상차단%d / "
        "실행대기%d 실행%d 복귀%d 실패%d / 원가없음%d (환율%.2f)",
        "실행ON" if _EXECUTE else "하드오프",
        summary["live_asks"],
        computed,
        dict(acts),
        len(cooldown),
        cd_blocked,
        anomaly_c,
        len(pending_exec),
        exec_ok,
        exec_revert,
        exec_fail,
        no_cost,
        rate,
    )
    if samples:
        logger.info("[크림섀도] 변동 샘플: %s", samples[:5])
    # 사이클 요약을 UI 로그에도 1줄 노출 (숫자 천단위 콤마)
    _emit_autotune_log(
        "KREAM",
        "",
        f"사이클 완료({'실행ON' if _EXECUTE else '섀도'}) — 입찰{summary['live_asks']:,} "
        f"계산{computed:,} 실행대기{len(pending_exec):,} 실행{exec_ok:,} 복귀{exec_revert:,} "
        f"실패{exec_fail:,} / 쿨다운보류{cd_blocked:,} 이상차단{anomaly_c:,} 원가없음{no_cost:,}",
    )
    await _flush_logs_to_db()
    return summary


# ══════════════════════════════════════════════════════════════════════════
# [Step 3] 스니덩크 전수순회 통합 루프 — 갱신 + 리스톡 + 삭제 한 흐름.
# 소싱처(SNKRDUNK) 매칭상품을 등록여부 무관 순회하며 옵션별로 분류:
#   재고O + live입찰O → 갱신(가격조정)   재고O + live입찰X → 리스톡(신규입찰)
#   재고X + live입찰O → 삭제              재고X + live입찰X → skip
# 카드(PSA)=snkr 실시간 fetch(원가·재고), 그외=DB options 폴백.
# 섀도(_EXECUTE 하드오프)=분류·로그만, PATCH/POST/DELETE 없음.
# KREAM_UNIFIED=1 일 때 lifecycle 이 run_kream_shadow_once 대신 이걸 호출.
# ══════════════════════════════════════════════════════════════════════════


def _decide_price_action(
    cur: int,
    opt: str,
    snkr_jpy: int,
    low_over: int,
    low_norm: int,
    cooldown_hit: bool,
    fixed: int,
    rate: float,
    tariff_threshold: int,
    is_box: bool = False,
    surcharge_rate: float | None = None,
) -> tuple[str, int, bool, bool]:
    """갱신 결정 — run_kream_shadow_once 결정로직과 동일. 반환 (act, target, adjusting, is_nocomp).
    로컬 _kream_ask_adjust rank1유도+5분기+rank2추종+안전장치 이식.
    is_box=True(박스/카드팩/신발) → 배송비 900엔. surcharge_rate 로 추가마진 분류 지정."""
    is_card = opt.upper().startswith("PSA")
    min_price = calc_min_price(snkr_jpy, rate, is_box, is_card, surcharge_rate)
    base = calc_base(snkr_jpy, rate, is_box, is_card, surcharge_rate)
    no_comp = (
        math.ceil(base * (1 + POLICY["no_competition_margin_rate"] / 100) / 1000) * 1000
    )
    is_ov = bool(low_over)
    market_low = (low_over if is_ov else low_norm) or low_over or low_norm
    rank1 = market_low > 0 and 0 < cur <= market_low
    no_comp_eff = min(no_comp, domestic_cap(low_norm, tariff_threshold))
    band = max(3000, int(no_comp_eff * 0.03))
    truly_nocomp = (rank1 or market_low >= no_comp_eff) and no_comp_eff > min_price

    act, target, is_nocomp = "유지", cur, False
    if rank1:
        if cur == min_price - 1000:
            act = "유지(동률)"
        elif cur < min_price:
            act, target = "마진미달인상", min_price
        elif market_low > 0 and cur < market_low - 1000:
            target = max(market_low - 1000, min_price)
            act = "경쟁추종인상" if target > cur else "유지"
        elif truly_nocomp and cur < no_comp_eff - band:
            if cooldown_hit:
                act = "무경쟁인상(쿨다운보류)"
            else:
                act, target, is_nocomp = "무경쟁인상", no_comp_eff, True
        elif truly_nocomp and cur > no_comp_eff + band:
            act, target = "과가격하향", no_comp_eff
    else:
        if is_ov:
            market_target = (low_over - 1000) if low_over > 0 else 0
        else:
            market_target = (low_norm - 5000) if low_norm > 0 else 0
        if market_target == 0:
            target = max(no_comp, min_price)
        elif market_target == min_price - 1000:
            target = min_price - 1000
        elif market_target <= min_price:
            target = min_price
        else:
            target = max(market_target, min_price)
        act = "no_rank1추종" if cur != target else "유지"

    if fixed:  # 지정가(사용자 확정가)
        target, act = fixed, ("지정가" if fixed != cur else "유지")
    adjusting = act not in ("유지", "유지(동률)", "무경쟁인상(쿨다운보류)")
    if adjusting and target < cur:  # 하향 20% 캡
        target = max(target, int(cur * (1 - _DROP_CAP)))
    if adjusting and market_low > 0 and target < market_low * _ANOMALY_FLOOR:
        act, target, adjusting = "이상감지차단", cur, False
    # ── 천원 단위 정규화 [필수] — 크림은 1,000원 단위만 허용("천원 단위로 입력하세요" 400).
    # 시장최저(-1000/-5000)·하향캡(cur×0.8)·지정가 경로에서 비(非)천원 값이 나와 PATCH가
    # 대량 실패하고 있었다. 절사 후 마진 하한 아래로 내려가면 하한으로 되올린다.
    if adjusting and target > 0:
        target = int(target) // 1000 * 1000
        if target < min_price:
            target = int(min_price) // 1000 * 1000
        if target == cur:
            adjusting = False
    # ── 데드밴드 — 미세 조정 생략(헛조정·API 소음 차단).
    # 예외 1) 마진 하한 미달 복구(손실 방지)
    # 예외 2) 1순위 획득 조정 — 크림은 1,000원 차이로 순위가 갈리므로 금액이 작아도
    #        실행해야 한다. 데드밴드를 여기까지 적용했더니 1,018건이 경쟁에서 이탈했다.
    _gains_rank1 = market_low > 0 and 0 < target <= market_low and not rank1
    if (
        adjusting
        and target != cur
        and cur > 0
        and cur >= min_price
        and not _gains_rank1
    ):
        _db = float(POLICY.get("adjust_deadband_pct") or 0)
        if _db > 0 and abs(target - cur) < max(cur * _db / 100, 1000):
            act, target, adjusting = "데드밴드생략", cur, False
    return act, target, adjusting, is_nocomp


async def _load_matched_products() -> list[dict]:
    """매칭 SNKRDUNK 상품 전량 — {snkr_id, kid, name, db_opts:{옵션:{price,stock}}, fixed:{옵션:가격}}.
    카드는 이후 snkr 실시간으로 덮어씀. 박스/기타는 이 DB 값(확장앱 수집) 사용."""
    out: list[dict] = []
    async with get_read_session() as s:
        rows = (
            await s.execute(
                _text(
                    "SELECT site_product_id AS snkr_id, "
                    "resell_matches->'kream'->>'product_id' AS kid, "
                    "options::text AS opts, name "
                    "FROM samba_collected_product WHERE source_site='SNKRDUNK' "
                    "AND COALESCE(resell_matches->'kream'->>'product_id','')<>''"
                )
            )
        ).all()
    for snkr_id, kid, opts_txt, name in rows:
        db_opts: dict = {}
        fixed: dict = {}
        if opts_txt:
            try:
                for o in json.loads(opts_txt):
                    if not (isinstance(o, dict) and o.get("name")):
                        continue
                    nm = str(o["name"])
                    db_opts[nm] = {
                        "price": int(o.get("price") or 0),
                        "stock": int(o.get("stock") or 0),
                    }
                    if o.get("fixedEnabled") and o.get("fixedPrice"):
                        fixed[nm] = int(o["fixedPrice"])
            except Exception:
                pass
        out.append(
            {
                "snkr_id": str(snkr_id or ""),
                "kid": str(kid or ""),
                "name": str(name or ""),
                "db_opts": db_opts,
                "fixed": fixed,
            }
        )
    return out


# ═══════════════════════════════════════════════════════════════════════════
# [Step 5] 리스톡/삭제 실행 + 로컬 봇 가드 이식 — 실제 POST/DELETE 안전 가드.
# 로컬 파일기반 상태(miss_counts/recent_posts/failed_posts)는 백엔드서 못 쓰므로 samba_settings
# JSON 으로 이관. 거래이력·이행대기는 DB 직조회. _EXECUTE 게이트로 섀도서 가드검증 후 실행 전환.
# ═══════════════════════════════════════════════════════════════════════════

# 등급(레어도) 토큰 = 낱장 카드 신호 (로컬 needs_trade 와 동일)
_GRADE_RE = re.compile(
    r"(?:\s|^)(SAR|CSR|CHR|RRR|VSTAR|VMAX|PROMO|LV\.X|HR|UR|SR|AR|RR|TR|GX|EX|ex|[UCRKSPV])(?=\s|:|\[|$)"
    r"|-ex(?:\s|$)"
)
# 리스톡 가드 상태(사이클 시작 시 로드): (kid,opt)→값
_g_trade_counts: dict[str, int] = {}
_g_unfulfilled: set[tuple[str, str]] = set()
_g_recent_posts: dict[str, float] = {}  # "kid|opt" → epoch (2h TTL)
_g_failed_posts: dict[str, float] = {}  # "kid|opt" → epoch (6h TTL)
_g_miss_counts: dict[str, int] = {}  # "kid|opt" → 연속 미검출 횟수
_RECENT_TTL = 7200
_FAILED_TTL = 21600
_SET_RECENT = "kream_recent_posts"
_SET_FAILED = "kream_failed_posts"
_SET_MISS = "kream_miss_counts"
# 입찰제한(최근 거래가 확인 필요) 반복 실패 쿨다운 — 공식 API 에 거래이력/허용밴드가 없어
# 재시도해도 계속 거절된다. 일정 시간 조정 대상서 제외해 헛호출·실패로그를 끊는다.
_SET_LIMIT = "kream_bid_limit_cooldown"
_LIMIT_TTL = 21600  # 6h
_g_limit_cd: dict = {}


def needs_trade(name: str) -> bool:
    """등록에 거래이력(≥1) 필요? 유희왕/원피스=필요, 포켓몬 낱장=불필요, 팩/박스=필요.
    로컬 _kream_restock_register.needs_trade 동일 포팅."""
    nm = name or ""
    t = nm.lower()
    if "유희왕" in nm or re.search(r"yu-?gi-?oh", t):
        return True
    if "원피스" in nm or re.search(r"one\s*piece", t):
        return True
    if _GRADE_RE.search(nm):
        return False
    if "박스" in nm or "팩" in nm:
        return True
    return False


async def _load_setting_map(key: str) -> dict:
    try:
        async with get_read_session() as s:
            v = (
                await s.execute(
                    _text("SELECT value FROM samba_settings WHERE key = :k"), {"k": key}
                )
            ).scalar_one_or_none()
        return dict(v) if isinstance(v, dict) else {}
    except Exception:
        return {}


async def _save_setting_map(key: str, data: dict) -> None:
    try:
        from backend.db.orm import get_write_session

        async with get_write_session() as s:
            await s.execute(
                _text(
                    "INSERT INTO samba_settings (key, value, updated_at) "
                    "VALUES (:k, CAST(:v AS json), NOW()) "
                    "ON CONFLICT (key) DO UPDATE SET value = CAST(:v AS json), updated_at = NOW()"
                ),
                {"k": key, "v": json.dumps(data, ensure_ascii=False)},
            )
            await s.commit()
    except Exception as exc:
        logger.warning("[크림통합] %s 저장 실패: %s", key, exc)


async def _load_setting_list(key: str) -> list:
    try:
        async with get_read_session() as s:
            v = (
                await s.execute(
                    _text("SELECT value FROM samba_settings WHERE key = :k"), {"k": key}
                )
            ).scalar_one_or_none()
        return list(v) if isinstance(v, list) else []
    except Exception:
        return []


async def _kream_autotune_enabled() -> bool:
    """오토튠 UI 소싱처(스니덩크) 체크상태 반영 — 스니덩크를 **명시적으로 체크해제**하면 스킵.
    기본 ON(saved_sources 빈목록=전체 or 스니덩크 포함). 판매처 KREAM 체크는 게이트 안 함
    (방금 추가돼 saved에 없는 게 정상이라 게이트하면 기본 OFF 오작동)."""
    try:
        srcs = await _load_setting_list("autotune_enabled_sources")
        if srcs and "SNKRDUNK" not in srcs:
            return False
    except Exception:
        pass
    return True


async def _load_restock_guards() -> None:
    """사이클 시작 시 리스톡 가드 상태 로드 — 거래이력·이행대기·재게시/실패/미검출 쿨다운."""
    import time as _t

    now = _t.time()
    _g_trade_counts.clear()
    _g_unfulfilled.clear()
    _g_recent_posts.clear()
    _g_failed_posts.clear()
    _g_miss_counts.clear()
    try:
        async with get_read_session() as s:
            for pid, ts in (
                await s.execute(
                    _text("SELECT product_id, total_sales FROM kream_trade_counts")
                )
            ).all():
                _g_trade_counts[str(pid)] = int(ts or 0)
            # 이행대기 — 소싱주문번호 없는 미이행 주문(판매 후 소싱 전 재입찰 보류)
            for kid, opt in (
                await s.execute(
                    _text(
                        "SELECT product_id AS kid, product_option AS opt FROM samba_order "
                        "WHERE order_number LIKE 'A-LI%' AND COALESCE(sourcing_order_number,'')='' "
                        "AND COALESCE(product_id,'')<>'' AND status NOT IN "
                        "('cancelled','cancel_requested','cancel_completed','cancel_release')"
                    )
                )
            ).all():
                _g_unfulfilled.add((str(kid), str(opt or "").replace(" ", "")))
    except Exception as exc:
        logger.warning("[크림통합] 거래이력/이행대기 로드 실패: %s", exc)
    rp = await _load_setting_map(_SET_RECENT)
    _g_recent_posts.update(
        {k: float(v) for k, v in rp.items() if now - float(v) < _RECENT_TTL}
    )
    fp = await _load_setting_map(_SET_FAILED)
    _g_failed_posts.update(
        {k: float(v) for k, v in fp.items() if now - float(v) < _FAILED_TTL}
    )
    _g_miss_counts.update(await _load_setting_map(_SET_MISS))


def _trade_ok(kid: str, name: str) -> bool:
    """거래이력 게이트 — needs_trade 상품은 누적거래수≥1 이어야 등록 허용."""
    if not needs_trade(name):
        return True
    return _g_trade_counts.get(str(kid), 0) >= 1


async def _exec_create_ask(
    cli: httpx.AsyncClient, h: dict, kid: str, price: int, opt: str
) -> tuple[bool, str]:
    """POST /asks 신규 입찰. 고시필요 응답이면 등록 재시도. 반환 (성공, 사유)."""
    try:
        r = await cli.post(
            f"{KREAM_OPENAPI_BASE}/asks",
            headers=h,
            json={"product_id": int(kid), "price": int(price), "option": opt},
        )
        if r.status_code in (200, 201):
            return True, "ok"
        detail = str((r.json() or {}).get("detail") or r.text)[:200]
        return False, detail
    except Exception as exc:
        return False, str(exc)[:120]


async def _exec_delete_ask(cli: httpx.AsyncClient, h: dict, ask_id) -> bool:
    try:
        r = await cli.delete(f"{KREAM_OPENAPI_BASE}/asks/{ask_id}", headers=h)
        return r.status_code in (200, 204)
    except Exception:
        return False


_SHOE_OPT_RE = re.compile(r"\d{3}(\.\d)?$")
# 신발 사이즈별 신품 최저가 — 상품페이지 SSR 내장 JSON. 카드(apparels 숫자ID)와 ID공간이
# 완전히 달라(/v1/apparels/{cid} 는 엉뚱한 의류 반환) 신발은 이 경로가 유일. 인증 불필요.
_SHOE_SIZE_RE = re.compile(r'"sizeName":"([^"]+)"[^}]*\},"minNewListingPrice":(\d+)')


def _cm_to_mm(s: str) -> str | None:
    """'26.5cm' → '265'(크림 ask 옵션 포맷). 형식 안 맞으면 None."""
    m = re.match(r"^(\d+(?:\.\d+)?)\s*cm$", (s or "").strip(), re.I)
    if not m:
        return None
    v = float(m.group(1)) * 10
    return str(int(v)) if v == int(v) else str(v)


async def _fetch_snkr_shoe_sizes(cli: httpx.AsyncClient, style: str) -> dict | None:
    """신발 사이즈별 실시간 최저가(신품) — {mm: {price, stock}}. 실패 시 None(=DB 폴백)."""
    try:
        r = await cli.get(
            f"https://snkrdunk.com/products/{style}",
            headers={
                "User-Agent": _SNKR_HEADERS["User-Agent"],
                "Accept-Language": "ja",
            },
            follow_redirects=True,
        )
        if r.status_code != 200:
            return None
        html = r.text.replace("\\", "")
    except Exception:
        return None
    out: dict = {}
    for sz, pr in _SHOE_SIZE_RE.findall(html):
        mm = _cm_to_mm(sz)
        p = int(pr)
        if mm and p > 0:
            out[mm] = {"price": p, "stock": 1}
    return out


async def _process_shoe_asks(
    asks: list,
    kid_to_opts: dict,
    cooldown,
    rate: float,
    tariff: int,
    h: dict,
    kid_to_snkr: dict | None = None,
) -> dict:
    """신발(mm 사이즈) ask 갱신/삭제 — 스니덩크 스니커즈.
    원가·재고는 수집된 DB 옵션(사이즈별 price/stock)을 사용 — 신발은 사이즈별 실시간
    시세 API가 없어 로컬 봇도 동일하게 DB 옵션을 썼다. 등록(리스톡)은 하지 않음.
    추가마진은 '나머지(신발·의류)' 정책값 적용, 배송비는 박스(900엔) 기준.
    가격 이상치(상식범위 밖)는 오염 데이터일 수 있어 건드리지 않고 보류 — 오조정 방지.
    _EXEC_SHOE=1 일 때만 실제 PATCH/DELETE."""
    shoe_asks = [
        a for a in asks if _SHOE_OPT_RE.fullmatch(str(a.get("option") or "").strip())
    ]
    c = {
        "total": len(shoe_asks),
        "renew": 0,
        "delete": 0,
        "hold": 0,
        "nocost": 0,
        "stock": 0,
        "patch": 0,
        "del": 0,
        "revert": 0,
        "fail": 0,
    }
    if not shoe_asks:
        return c
    _sur = POLICY["non_card_margin_rate"]  # 신발 = 비카드 추가마진
    kid_to_snkr = kid_to_snkr or {}
    async with httpx.AsyncClient(timeout=25) as cli:
        # 상품별 실시간 사이즈시세 1회 조회(입찰이 여러 사이즈여도 페이지는 1번만) — DB 폴백
        live_map: dict = {}
        _sem = asyncio.Semaphore(6)

        async def _one_style(kid: str):
            style = kid_to_snkr.get(kid)
            if not style:
                return
            async with _sem:
                live = await _fetch_snkr_shoe_sizes(cli, style)
            if live is not None:
                live_map[kid] = live

        await asyncio.gather(
            *[
                _one_style(k)
                for k in {str(a.get("product_id") or "") for a in shoe_asks}
            ]
        )
        c["live_ok"] = len(live_map)

        for a in shoe_asks:
            kid = str(a.get("product_id") or "")
            opt = str(a.get("option") or "").strip()
            # 실시간 우선: 조회 성공한 상품은 그 값이 진실(매물 없으면 재고0=삭제 후보)
            if kid in live_map:
                od = live_map[kid].get(opt) or {"price": 0, "stock": 0}
            else:
                od = (kid_to_opts.get(kid) or {}).get(opt)
            if od is None:
                c["nocost"] += 1
                continue
            price = int(od.get("price") or 0)
            stock = int(od.get("stock") or 0)
            # 오염 가드 — 신발 원가 상식범위 밖이면 조정/삭제 모두 보류(수집 파싱오류 방어)
            if price and not (5000 <= price <= 300000):
                c["hold"] += 1
                continue
            # 입찰 최고 원가 초과 — 갱신 제외(체결 시 그 값으로 소싱해야 해 치명적)
            if price > POLICY["max_cost_jpy"]:
                c["overcost"] = c.get("overcost", 0) + 1
                continue
            if stock <= 0 or price <= 0:
                c["delete"] += 1
                if _EXEC_SHOE:
                    if a.get("id") and await _exec_delete_ask(cli, h, a.get("id")):
                        c["del"] += 1
                    else:
                        c["fail"] += 1
                    await asyncio.sleep(0.1)
                continue
            c["stock"] += 1
            cur = int(a.get("price") or 0)
            _floor_map[(kid, opt)] = calc_min_price(price, rate, True, False, _sur)
            act, target, adjusting, is_nc = _decide_price_action(
                cur,
                opt,
                price,
                int(a.get("lowest_overseas_price") or 0),
                int(a.get("lowest_normal_price") or 0),
                (kid, opt) in cooldown,
                0,
                rate,
                tariff,
                is_box=True,
                surcharge_rate=_sur,
            )
            if adjusting and target != cur:
                c["renew"] += 1
                if _EXEC_SHOE and a.get("id"):
                    res, _r = await _execute_update(
                        cli, h, a.get("id"), target, cur, is_nc, kid, opt
                    )
                    if res == "ok":
                        c["patch"] += 1
                    elif res == "reverted":
                        c["revert"] += 1
                    else:
                        c["fail"] += 1
                    await asyncio.sleep(0.1)
    return c


async def _process_box_asks(
    asks: list, kid_to_snkr: dict, cooldown, rate: float, tariff: int, h: dict
) -> dict:
    """박스(해외배송) ask 갱신/삭제 — snkr 박스시세(/v1/apparels) 실시간. 리스톡 미포함.
    _EXEC_BOX=1 일 때만 실제 PATCH/DELETE. API실패(-1)는 삭제금지(보류)."""
    box_asks = [a for a in asks if "해외배송" in str(a.get("option") or "")]
    c = {
        "total": len(box_asks),
        "renew": 0,
        "delete": 0,
        "hold": 0,
        "nocost": 0,
        "patch": 0,
        "del": 0,
        "revert": 0,
        "fail": 0,
    }
    if not box_asks:
        return c
    sem = asyncio.Semaphore(6)
    async with httpx.AsyncClient(timeout=20) as scli:

        async def _one(a):
            async with sem:
                kid = str(a.get("product_id") or "")
                snkr_id = kid_to_snkr.get(kid)
                if not snkr_id:
                    return ("nocost", a, 0, False)
                box = await _fetch_snkr_box(scli, snkr_id)
                if box["stock"] < 0:
                    return ("hold", a, 0, False)  # API 실패 — 삭제금지
                if box["stock"] == 0 or box["price"] <= 0:
                    return ("delete", a, 0, False)
                # 입찰 최고 원가 초과 — 갱신 대상서 제외(로컬 25만엔 원칙). 삭제는 안 함.
                if box["price"] > POLICY["max_cost_jpy"]:
                    return ("overcost", a, 0, False)
                cur = int(a.get("price") or 0)
                _floor_map[(kid, "해외배송")] = calc_min_price(
                    box["price"], rate, True, False
                )
                act, target, adjusting, is_nc = _decide_price_action(
                    cur,
                    "해외배송",
                    box["price"],
                    int(a.get("lowest_overseas_price") or 0),
                    int(a.get("lowest_normal_price") or 0),
                    (kid, "해외배송") in cooldown,
                    0,
                    rate,
                    tariff,
                    is_box=True,
                )
                return (
                    ("renew" if adjusting and target != cur else "keep"),
                    a,
                    target,
                    is_nc,
                    act,
                    box["price"],
                )

        rows = await asyncio.gather(
            *[_one(a) for a in box_asks], return_exceptions=True
        )
        _bsamp: list = []
        for row in rows:
            if isinstance(row, Exception) or not isinstance(row, tuple):
                c["hold"] += 1
                continue
            kind, a, target, is_nc = row[0], row[1], row[2], row[3]
            _bact = row[4] if len(row) > 4 else ""
            _bjpy = row[5] if len(row) > 5 else 0
            if kind == "overcost":
                c["overcost"] = c.get("overcost", 0) + 1
            elif kind == "nocost":
                c["nocost"] += 1
            elif kind == "hold":
                c["hold"] += 1
            elif kind == "delete":
                c["delete"] += 1
                if _EXEC_BOX:
                    if await _exec_delete_ask(scli, h, a.get("id")):
                        c["del"] += 1
                    else:
                        c["fail"] += 1
                    await asyncio.sleep(0.1)
            elif kind == "renew":
                c["renew"] += 1
                if len(_bsamp) < 8:
                    _bsamp.append(
                        f"{a.get('product_id')} ¥{_bjpy:,} {int(a.get('price') or 0):,}→{target:,}[{_bact}]"
                    )
                if _EXEC_BOX:
                    res, _r = await _execute_update(
                        scli,
                        h,
                        a.get("id"),
                        target,
                        int(a.get("price") or 0),
                        is_nc,
                        str(a.get("product_id")),
                        "해외배송",
                    )
                    if res == "ok":
                        c["patch"] += 1
                    elif res == "reverted":
                        c["revert"] += 1
                    else:
                        c["fail"] += 1
                    await asyncio.sleep(0.1)
    if _bsamp:
        logger.info("[크림통합] 박스 변동샘플: %s", _bsamp)
    return c


async def run_kream_unified_once() -> dict:
    """[Step 3 섀도] 스니덩크 전수순회 통합 — 옵션별 갱신/리스톡/삭제 분류. 쓰기 없음(하드오프)."""
    from collections import Counter as _Counter

    if not await _kream_autotune_enabled():
        logger.info("[크림통합] 오토튠 UI서 스니덩크/크림 체크해제 — 이번 사이클 스킵")
        _emit_autotune_log("KREAM", "", "[통합] 스니덩크/크림 체크해제 — 스킵")
        await _flush_logs_to_db()
        return {"ok": True, "reason": "disabled"}

    service, key, secret = await _load_kream_creds()
    if not (service and key and secret):
        logger.warning("[크림통합] 인증정보 없음 — 스킵")
        return {"ok": False, "reason": "no_creds"}
    h = _headers(service, key, secret)
    try:
        asks = await _fetch_live_asks(h)
    except Exception as exc:
        logger.warning("[크림통합] live 입찰 조회 실패: %s", exc)
        return {"ok": False, "reason": f"fetch_error: {exc}"}

    await _load_policy()
    _fail_reasons.clear()  # 사이클 단위 실패사유 집계
    _hb_clamp["used"] = 0  # 입찰제한 보정 상한 리셋
    _rank_fix["used"] = 0  # 순위교정 상한 리셋
    _floor_map.clear()
    # 입찰제한 쿨다운 로드(만료 정리) — 반복 실패 건을 이번 사이클 조정에서 제외
    _g_limit_cd.clear()
    _now_l = _now_ts()
    for _k, _v in (await _load_setting_map(_SET_LIMIT)).items():
        try:
            if _now_l - float(_v) < _LIMIT_TTL:
                _g_limit_cd[_k] = float(_v)
        except Exception:
            pass
    cooldown = await _load_cooldown()
    rate = await _jpy_krw_rate()
    tariff_threshold = int(150 * await _usd_krw_rate())

    # live ask 인덱스 (kid, 옵션) → ask
    ask_index: dict = {}
    for a in asks:
        ask_index[(str(a.get("product_id") or ""), str(a.get("option") or ""))] = a

    products = await _load_matched_products()
    # 박스 pass용 kid→snkr_id 맵 (배치 슬라이스 전 전체 — 박스 ask는 카탈로그 전역, 로테이션 안 함)
    kid_to_snkr = {
        p["kid"]: p["snkr_id"] for p in products if p["kid"] and p["snkr_id"]
    }
    # 신발 pass용 kid→옵션맵 (사이즈별 price/stock). 배치 슬라이스 전 전체 — 신발 ask도 전역.
    kid_to_opts = {p["kid"]: p["db_opts"] for p in products if p["kid"]}
    # ── 처리 대상 선정 [2026-07-22 구조개선] — 갱신과 리스톡의 필요 주기가 다름.
    #  · 갱신(live 입찰 보유): 시세 추종이라 **매 사이클 전량** 처리해야 경쟁에서 안 밀림.
    #    (로컬 봇도 live 입찰은 매 라운드 조정했음. 로테이션에 넣으면 1회전 1.7시간 = 사실상 방치)
    #  · 리스톡 탐색(live 입찰 없음): 신규 재고 발굴이라 급하지 않음 → 나머지만 BATCH 로테이션.
    # 결과: 갱신 5분 주기 + 리스톡 탐색은 계속 순회. 스니덩크 fetch 부담도 상한 유지.
    global _unified_offset
    total_products = len(products)
    _live_kids = {k for (k, _o) in ask_index}
    live_products = [p for p in products if p["kid"] in _live_kids]
    rest_products = [p for p in products if p["kid"] not in _live_kids]
    batch = int(os.environ.get("KREAM_UNIFIED_BATCH") or 10000)
    if batch > 0 and len(rest_products) > batch:
        start = _unified_offset % len(rest_products)
        rest_slice = (rest_products[start:] + rest_products[:start])[:batch]
        _unified_offset = (start + batch) % len(rest_products)
    else:
        rest_slice = rest_products
        _unified_offset = 0
    products = live_products + rest_slice
    rest_total = len(rest_products)  # 리스톡 탐색 로테이션 분모(진행률 표시용)
    logger.info(
        "[크림통합] 대상선정 — 갱신(live)%d 전량 + 리스톡탐색 %d/%d (offset %d)",
        len(live_products),
        len(rest_slice),
        len(rest_products),
        _unified_offset,
    )

    acts: _Counter = _Counter()
    counts = {
        "products": 0,
        "options": 0,
        "cards": 0,
        "noncard": 0,
        "snkr_ok": 0,
        "snkr_fail": 0,
        "renew": 0,
        "restock": 0,
        "delete": 0,
        "cd_blocked": 0,
        "anomaly": 0,
    }
    samples: list[dict] = []
    sem = asyncio.Semaphore(8)

    _emit_autotune_log(
        "KREAM",
        "",
        f"[통합] 사이클 시작 — 매칭상품 {len(products):,} live입찰 {len(asks):,} "
        f"({'실행ON' if _EXECUTE else '섀도'})",
    )

    async def _process(prod: dict, scli: httpx.AsyncClient) -> dict:
        async with sem:
            snkr_id = prod["snkr_id"]
            kid = prod["kid"]
            r = {"snkr_ok": 0, "snkr_fail": 0, "noncard": 0, "card": 0, "rows": []}
            # [Step 3 완성] 카드(PSA) 경로만 처리 — 신발(KREAM옵션 mm '270' ↔ DB 'cm')·
            # 박스(KREAM '해외배송' ↔ DB '1個')는 옵션명 매핑이 달라 오작동(false 리스톡) 위험 →
            # 로컬 봇에 위임. 카드 판정: DB 옵션에 PSA 존재. 비카드는 snkr fetch 없이 즉시 skip.
            has_psa_opt = any("PSA" in str(n).upper() for n in prod["db_opts"])
            if not has_psa_opt:
                r["noncard"] = 1
                return r
            live = await _fetch_snkr_used(scli, snkr_id) if snkr_id else None
            if live is None:
                r["snkr_fail"] = 1
                return r
            r["snkr_ok"] = 1
            r["card"] = 1
            # 매수추천/원가오염 감시용 스냅샷 (PSA10 고점대비 급락 판정)
            _p10 = live.get("PSA 10") or {}
            _p9 = live.get("PSA 9") or {}
            r["psa"] = (
                kid,
                snkr_id,
                int(_p10.get("price") or 0),
                int(_p10.get("stock") or 0),
                int(_p9.get("price") or 0),
                int(_p9.get("stock") or 0),
            )
            # 슬랙 '재고 N건(카드…)' 집계 — 매물 있는 카드 상품 수
            if int(_p10.get("stock") or 0) > 0 or int(_p9.get("stock") or 0) > 0:
                r["instock"] = 1
            # PSA10/PSA9만 — 카드는 실시간 snkr(/used) 원가·재고 신뢰
            for nm in ("PSA 10", "PSA 9"):
                d = live.get(nm) or {}
                price = int(d.get("price") or 0)
                stock = int(d.get("stock") or 0)
                ask = ask_index.get((kid, nm))
                has_ask = ask is not None
                # 입찰 최고 원가 초과 — 갱신·리스톡 모두 제외(로컬 25만엔 원칙).
                # 체결되면 그 원가로 소싱해야 해 초고가 카드는 애초에 다루지 않는다.
                if price > POLICY["max_cost_jpy"]:
                    r["rows"].append(
                        (
                            "overcost",
                            "원가상한초과",
                            kid,
                            nm,
                            0,
                            0,
                            False,
                            prod["name"],
                            False,
                        )
                    )
                    continue
                if has_ask and stock > 0 and price > 0:
                    cur = int(ask.get("price") or 0)
                    low_over = int(ask.get("lowest_overseas_price") or 0)
                    low_norm = int(ask.get("lowest_normal_price") or 0)
                    # 입찰제한 쿨다운 — 크림이 계속 거절하는 건은 재시도 안 함
                    if f"{kid}|{nm}" in _g_limit_cd:
                        r["rows"].append(
                            (
                                "skip",
                                "입찰제한쿨다운",
                                kid,
                                nm,
                                cur,
                                cur,
                                False,
                                prod["name"],
                                False,
                            )
                        )
                        continue
                    # 순위교정용 마진 하한 기록 (이 아래로는 안 내림)
                    _floor_map[(kid, nm)] = calc_min_price(
                        price, rate, False, nm.upper().startswith("PSA")
                    )
                    act, target, adjusting, is_nc = _decide_price_action(
                        cur,
                        nm,
                        price,
                        low_over,
                        low_norm,
                        (kid, nm) in cooldown,
                        prod["fixed"].get(nm, 0),
                        rate,
                        tariff_threshold,
                    )
                    r["rows"].append(
                        (
                            "renew",
                            act,
                            kid,
                            nm,
                            cur,
                            target,
                            adjusting,
                            prod["name"],
                            is_nc,
                        )
                    )
                elif has_ask and stock <= 0:
                    r["rows"].append(
                        (
                            "delete",
                            "삭제(무재고)",
                            kid,
                            nm,
                            int(ask.get("price") or 0),
                            0,
                            True,
                            prod["name"],
                            False,
                        )
                    )
                elif not has_ask and stock > 0 and price > 0:
                    base = calc_base(price, rate, False, True)
                    mp = calc_min_price(price, rate, False, True)
                    nc = (
                        math.ceil(
                            base
                            * (1 + POLICY["no_competition_margin_rate"] / 100)
                            / 1000
                        )
                        * 1000
                    )
                    r["rows"].append(
                        (
                            "restock",
                            "리스톡",
                            kid,
                            nm,
                            0,
                            max(nc, mp),
                            True,
                            prod["name"],
                            False,
                        )
                    )
                # stock<=0 & no ask → 무동작(카운트 안 함)
            return r

    _emitted = 0
    async with httpx.AsyncClient(timeout=20) as scli:
        results = await asyncio.gather(
            *[_process(p, scli) for p in products], return_exceptions=True
        )

    # [Step 5] 리스톡 가드 상태 로드 + 실행대기 수집(순차 — 가드상태 race 방지)
    await _load_restock_guards()
    import time as _t  # noqa: F811

    _now = _t.time()
    pend_renew: list = []  # (kid, nm, target, cur, is_nc)
    pend_restock: list = []  # (kid, nm, target, pname)
    pend_delete: list = []  # (kid, nm)
    rs = {"recent": 0, "failed": 0, "miss": 0, "trade": 0, "hold": 0, "ok": 0}
    psa_snapshot: list = []  # 매수추천/원가오염 감시용 (kid, snkr_id, p10가, p10재고, p9가, p9재고)
    card_instock = 0  # 매물 있는 카드 상품 수 (슬랙 '재고 N건(카드…)')

    for res in results:
        if isinstance(res, Exception) or not isinstance(res, dict):
            counts["snkr_fail"] += 1
            continue
        counts["products"] += 1
        counts["snkr_ok"] += res["snkr_ok"]
        counts["snkr_fail"] += res["snkr_fail"]
        counts["noncard"] += res.get("noncard", 0)
        counts["cards"] += res.get("card", 0)
        if res.get("psa"):
            psa_snapshot.append(res["psa"])
        card_instock += res.get("instock", 0)
        for kind, act, kid, nm, cur, target, adjusting, pname, is_nc in res["rows"]:
            counts["options"] += 1
            acts[act] += 1
            if kind == "overcost":
                counts["overcost"] = counts.get("overcost", 0) + 1
            elif kind == "renew":
                counts["renew"] += 1
                if act == "무경쟁인상(쿨다운보류)":
                    counts["cd_blocked"] += 1
                if act == "이상감지차단":
                    counts["anomaly"] += 1
                if adjusting and target != cur:
                    pend_renew.append((kid, nm, target, cur, is_nc))
            elif kind == "delete":
                counts["delete"] += 1
                pend_delete.append((kid, nm))
            elif kind == "restock":
                counts["restock"] += 1
                # 리스톡 가드 (로컬 순서: 2연속miss → 재게시2h → 실패6h → 거래이력 → 이행대기)
                _key = f"{kid}|{nm}"
                _g_miss_counts[_key] = int(_g_miss_counts.get(_key, 0)) + 1
                if _g_miss_counts[_key] < 2:
                    rs["miss"] += 1
                elif _key in _g_recent_posts:
                    rs["recent"] += 1
                elif _key in _g_failed_posts:
                    rs["failed"] += 1
                elif not _trade_ok(kid, pname):
                    rs["trade"] += 1
                elif (str(kid), nm.replace(" ", "")) in _g_unfulfilled:
                    rs["hold"] += 1
                else:
                    rs["ok"] += 1
                    pend_restock.append((kid, nm, target, pname))
            if act not in ("유지", "유지(동률)"):
                if _emitted < 120:
                    _emitted += 1
                    _pn = str(pname or "")[:40]
                    if kind == "restock":
                        _emit_autotune_log(
                            "KREAM", kid, f"{_pn} ({nm}): 리스톡 신규입찰 {target:,}"
                        )
                    elif kind == "delete":
                        _emit_autotune_log(
                            "KREAM", kid, f"{_pn} ({nm}): 무재고 삭제 (현재 {cur:,})"
                        )
                    elif target != cur:
                        _emit_autotune_log(
                            "KREAM",
                            kid,
                            f"{_pn} ({nm}): 가격변동 {cur:,}→{target:,} [{act}]",
                        )
                if len(samples) < 10:
                    samples.append(
                        {
                            "kid": kid,
                            "opt": nm,
                            "cur": cur,
                            "target": target,
                            "act": act,
                            "kind": kind,
                        }
                    )

    # ── [Step 5] 실제 실행 — _EXECUTE=1 일 때만. 삭제→갱신→리스톡 순. rate limit 여유(0.1s).
    # 로그는 실행 진행 중 5건마다 DB flush — 사이클 끝까지 안 기다리고 UI에 즉시 노출.
    exec_patch = exec_post = exec_del = exec_fail = exec_revert = 0
    registered_lines: list = []  # 슬랙 리스톡 섹션 — 실제 등록된 (상품 옵션 가격) 줄
    await _flush_logs_to_db()  # 분류 결과 먼저 노출(실행 시작 전)
    if _EXECUTE:
        async with httpx.AsyncClient(timeout=25) as ecli:
            for _i, (kid, nm) in enumerate(pend_delete):
                ask = ask_index.get((kid, nm))
                if ask and await _exec_delete_ask(ecli, h, ask.get("id")):
                    exec_del += 1
                else:
                    exec_fail += 1
                if (_i + 1) % 5 == 0:
                    await _flush_logs_to_db()
                await asyncio.sleep(0.1)
            await _flush_logs_to_db()
            for _i, (kid, nm, target, cur, is_nc) in enumerate(pend_renew):
                ask = ask_index.get((kid, nm))
                if not ask:
                    continue
                res2, _rank = await _execute_update(
                    ecli, h, ask.get("id"), target, cur, is_nc, kid, nm
                )
                if res2 == "ok":
                    exec_patch += 1
                elif res2 == "reverted":
                    exec_revert += 1
                else:
                    exec_fail += 1
                if (_i + 1) % 5 == 0:
                    await _flush_logs_to_db()
                await asyncio.sleep(0.1)
            await _flush_logs_to_db()
            for _i, (kid, nm, target, pname) in enumerate(pend_restock):
                ok2, reason = await _exec_create_ask(ecli, h, kid, target, nm)
                if (not ok2) and ("announcement" in reason or "고시" in reason):
                    ok2, reason = await _exec_create_ask(ecli, h, kid, target, nm)
                if ok2:
                    exec_post += 1
                    # 슬랙 리스톡 섹션 등록줄 (로컬 포맷: "{상품명20} {옵션} {가격}원")
                    registered_lines.append(f"{str(pname)[:20]} {nm} {target:,}원")
                    _g_recent_posts[f"{kid}|{nm}"] = _now
                    _g_miss_counts.pop(f"{kid}|{nm}", None)
                else:
                    exec_fail += 1
                    _g_failed_posts[f"{kid}|{nm}"] = _now
                if (_i + 1) % 5 == 0:
                    await _flush_logs_to_db()
                await asyncio.sleep(0.1)
            await _flush_logs_to_db()
        await _save_setting_map(_SET_RECENT, _g_recent_posts)
        await _save_setting_map(_SET_FAILED, _g_failed_posts)
    await _save_setting_map(
        _SET_MISS, _g_miss_counts
    )  # 2연속 대기 상태는 섀도서도 유지
    await _save_setting_map(_SET_LIMIT, _g_limit_cd)  # 입찰제한 쿨다운 유지

    # ── [B] 신발(mm) 갱신/삭제 — 전역 ask 대상. DB 옵션(사이즈별) 원가. _EXEC_SHOE 게이트.
    shoe = await _process_shoe_asks(
        asks, kid_to_opts, cooldown, rate, tariff_threshold, h, kid_to_snkr
    )
    logger.info(
        "[크림통합] 신발(mm) %d — 실시간%d 재고%d 갱신%d 삭제%d 보류%d 원가없음%d / 실행[갱신%d 삭제%d 복귀%d 실패%d] (%s)",
        shoe["total"],
        shoe.get("live_ok", 0),
        shoe["stock"],
        shoe["renew"],
        shoe["delete"],
        shoe["hold"],
        shoe["nocost"],
        shoe["patch"],
        shoe["del"],
        shoe["revert"],
        shoe["fail"],
        "실행ON" if _EXEC_SHOE else "섀도",
    )
    if shoe["total"]:
        _emit_autotune_log(
            "KREAM",
            "",
            f"[신발] mm {shoe['total']:,} — 갱신{shoe['renew']:,} 삭제{shoe['delete']:,} "
            f"보류{shoe['hold']:,} / 실행 갱신{shoe['patch']:,} 삭제{shoe['del']:,} "
            f"복귀{shoe['revert']:,} 실패{shoe['fail']:,} "
            f"({'실행ON' if _EXEC_SHOE else '섀도'})",
        )

    # ── [A] 박스(해외배송) 갱신/삭제 — 전역 ask 대상(배치 무관). _EXEC_BOX 게이트.
    box = await _process_box_asks(
        asks, kid_to_snkr, cooldown, rate, tariff_threshold, h
    )
    logger.info(
        "[크림통합] 박스(해외배송) %d — 갱신%d 삭제%d 보류%d 원가없음%d / 실행[갱신%d 삭제%d 복귀%d 실패%d] (%s)",
        box["total"],
        box["renew"],
        box["delete"],
        box["hold"],
        box["nocost"],
        box["patch"],
        box["del"],
        box["revert"],
        box["fail"],
        "실행ON" if _EXEC_BOX else "섀도",
    )
    if box["total"]:
        _emit_autotune_log(
            "KREAM",
            "",
            f"[박스] 해외배송 {box['total']:,} — 갱신{box['renew']:,} 삭제{box['delete']:,} "
            f"보류{box['hold']:,} / 실행 갱신{box['patch']:,} 삭제{box['del']:,} 복귀{box['revert']:,} "
            f"실패{box['fail']:,} ({'실행ON' if _EXEC_BOX else '섀도'})",
        )

    logger.info(
        "[크림통합] %s — 상품%d(카드%d 비카드%d snkr실패%d) / 갱신%d 리스톡%d(가능%d 2연속대기%d "
        "재게시%d 실패쿨%d 거래게이트%d 이행대기%d) 삭제%d / 쿨다운보류%d 이상차단%d "
        "/ 실행[갱신%d 등록%d 삭제%d 복귀%d 실패%d] (환율%.2f offset%d/%d)",
        "실행ON" if _EXECUTE else "섀도(하드오프)",
        counts["products"],
        counts["cards"],
        counts["noncard"],
        counts["snkr_fail"],
        counts["renew"],
        counts["restock"],
        rs["ok"],
        rs["miss"],
        rs["recent"],
        rs["failed"],
        rs["trade"],
        rs["hold"],
        counts["delete"],
        counts["cd_blocked"],
        counts["anomaly"],
        exec_patch,
        exec_post,
        exec_del,
        exec_revert,
        exec_fail,
        rate,
        _unified_offset,
        rest_total,
    )
    if samples:
        logger.info("[크림통합] 샘플: %s", samples[:5])
    _emit_autotune_log(
        "KREAM",
        "",
        f"[통합] 사이클 완료({'실행ON' if _EXECUTE else '섀도'}) — 카드{counts['cards']:,} "
        f"/ 갱신{counts['renew']:,} 리스톡가능{rs['ok']:,}(보류 {counts['restock'] - rs['ok']:,}) "
        f"삭제{counts['delete']:,} 원가상한초과{counts.get('overcost', 0):,} / 실행 갱신{exec_patch:,} 등록{exec_post:,} 삭제{exec_del:,} "
        f"복귀{exec_revert:,} 실패{exec_fail:,} (리스톡탐색 {min(_unified_offset, rest_total):,}/{rest_total:,})",
    )
    await _flush_logs_to_db()
    # 활성사이클 표시용 상태 기록 (카드 갱신+박스 갱신 = 가격조정 건수)
    await _save_kream_cycle_status(
        min(_unified_offset, rest_total),
        rest_total,
        counts["renew"] + box.get("renew", 0),
        counts["delete"] + box.get("delete", 0),
    )
    # ── 슬랙 알림 [로컬 봇 이식] — 사이클마다 실행 요약. 무변동이어도 발송(로컬과 동일).
    # 로컬과 동일한 구성: 미이행 + 방치입찰(고아) + 매수추천/원가오염 + 실행요약.
    _mode = "실행" if _EXECUTE else "섀도"
    _unf = await _unfulfilled_count()
    _pre = f"⚠️ 미이행 크림주문 {_unf:,}건 (소싱 필요)\n" if _unf > 0 else ""
    try:
        _pre += await _orphan_report(asks, kid_to_snkr, h)
    except Exception as _oe:
        logger.warning("[크림통합] 방치입찰 알림 실패(무시): %s", _oe)
    try:
        _pre += await _buy_watch(psa_snapshot)
    except Exception as _be:
        logger.warning("[크림통합] 매수추천 알림 실패(무시): %s", _be)
    # ── 본문: 로컬 봇 슬랙 포맷 그대로 재현 (구분선 길이·문구·조건까지 동일) ──
    _r1, _n1, _gt, _nc = _rank_summary(asks)
    _ask_kids = {str(a.get("product_id") or "") for a in asks}
    _mapped = len([k for k in _ask_kids if k in kid_to_snkr])
    _del_all = exec_del + int(box.get("del", 0))
    _upd_all = exec_patch + int(box.get("patch", 0))
    _fail_all = exec_fail + int(box.get("fail", 0))
    # [일치상품 리스톡·미등록 점검] — 로컬 _kream_restock_register 요약 포맷
    _box_stock = max(0, int(box.get("total", 0)) - int(box.get("nocost", 0)))
    _shoe_stock = int(shoe.get("stock", 0))
    _stock_total = card_instock + _shoe_stock + _box_stock
    _restock_sec = (
        f"[일치상품 리스톡·미등록 점검]\n"
        f"재고 {_stock_total:,}건 (카드 {card_instock:,}·신발 {_shoe_stock:,}"
        f"·박스/팩 {_box_stock:,})"
        f" / 신규등록 {exec_post:,}건 / 실패 {exec_fail:,}"
    )
    if registered_lines:
        _restock_sec += "\n" + "\n".join(registered_lines[:10])
        if len(registered_lines) > 10:
            _restock_sec += f"\n외 {len(registered_lines) - 10:,}건"
    _restock_sec += "\n━━━━━━━━━━\n"
    _msg = (
        f"[크림 입찰갱신]\n"
        f"환율 {rate:.4f} JPY→KRW\n\n"
        f"입찰 {len(asks):,}건 | 매핑 {_mapped:,}/{len(_ask_kids):,}건\n"
        f"삭제 {_del_all:,}건 | 조정 {_upd_all:,}건"
        + (f" | ❌갱신실패 {_fail_all:,}건" if _fail_all else "")
        + f"\n1순위(국내포함) {_r1:,} / 비1순위 {_n1:,} (그룹 {_gt:,})\n"
        f"무경쟁 후보(국내없음·내입찰연속) {_nc:,}그룹"
    )
    # 갱신실패 사유 breakdown — 실패 건수만 보이고 원인을 몰라 대응 못 하던 것 보완(로컬 포맷).
    if _fail_reasons:
        _top = sorted(_fail_reasons.items(), key=lambda kv: -kv[1])[:5]
        _msg += "\n\n⚠️ 갱신실패 사유:\n  " + "\n  ".join(
            f"{k}: {v:,}건" for k, v in _top
        )
    if counts["anomaly"]:
        _msg += f"\n\n⚠️ 이상감지(가격오류 의심·갱신차단) {counts['anomaly']:,}건"
    await _send_slack(_pre + _restock_sec + _msg)
    return {
        "ok": True,
        "counts": counts,
        "restock_guard": rs,
        "executed": {
            "patch": exec_patch,
            "post": exec_post,
            "delete": exec_del,
            "revert": exec_revert,
            "fail": exec_fail,
        },
        "samples": samples,
    }
