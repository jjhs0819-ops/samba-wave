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
import itertools
import json
import logging
import math
import os
import re
import time as _time_mod

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
# 신발(mm) 갱신/삭제 실행 게이트 — 섀도 검증 후 KREAM_EXEC_SHOE=1.
_EXEC_SHOE = os.environ.get("KREAM_EXEC_SHOE") == "1"
# 신발 신규 자동등록 실행 게이트 — 갱신/삭제와 별도. 섀도 후보 검증 후 KREAM_EXEC_SHOE_RESTOCK=1.
_EXEC_SHOE_RESTOCK = os.environ.get("KREAM_EXEC_SHOE_RESTOCK") == "1"

# ── 사이클 상한 [2026-08-04 일원화] ──────────────────────────────────────────
# 종전엔 카드·신발·박스가 제각각 다른 상한으로 돌았다(갱신 2,500 / 신발조회 7,000 /
# 신발등록 50 / 박스등록 30 / 만료회수 30 …). 어느 쪽이 병목인지 알 수 없었고,
# 신발 등록 50 은 미등록 19,804건을 사실상 방치했다. 두 개로 줄인다.
# 카테고리별 환경변수를 주면 그쪽이 우선 — 급할 때 미세조정 여지는 남긴다.
# 사이클 상한·로테이션 전면 제거 [2026-08-04].
# 카드·신발·박스가 제각각 다른 상한(갱신2,500 / 신발조회7,000 / 신발등록50 / 박스등록30 /
# 만료회수30 / 가격열위삭제2,000)으로 나눠 돌면서, 자기 차례를 기다리는 동안 밀린 입찰이
# 방치되고 신규 브랜드는 사실상 등록되지 않았다(아디다스 재고 4,484 → 입찰 44).
# 이제 매 사이클 전량을 조회·판정·실행한다. 사이클은 길어지지만 배포 가드가 완주를 기다린다.
# 비카드 우선처리는 전량 처리라 의미가 없어졌지만, 호출부 호환을 위해 큰 값으로 남긴다.
# [2026-08-05] 비카드 우선처리 폐기 — 리스톡 슬라이스가 재고 보유 우선으로 정렬되므로
# 신발·의류도 이미 앞줄에서 뽑힌다. 슬라이스 밖에서 따로 더 넣을 이유가 없어졌고,
# 무제한으로 열려 있던 탓에 리스톡을 1만으로 줄여도 1.9만이 다시 들어와 분리가
# 무력화됐다(실측: 갱신 11,879 + 리스톡 10,000 = 21,879 인데 조회 대상 41,286).
# [2026-08-05] 기본 상한 폐기(0=무제한). 비카드는 17,014 상품인데 3,000 에서 잘려
# 나머지 14,000 이 매 사이클 **로그도 카운트도 없이** return 됐다. "왜 등록이 안 되는지
# 모르겠다"의 정체가 이것. 슬라이스(리스톡 1만)가 이미 총량을 제한하므로 이중 상한이다.
_NONCARD_PROBE_MAX = int(os.environ.get("KREAM_NONCARD_PROBE_MAX") or 0)
_noncard_probe_used = 0  # 사이클당 비카드 크림조회 사용량(사이클 시작 시 리셋)
# 프로세스 기동 후 첫 사이클인가 — 첫 사이클은 스캔목록을 리셋하고 처음부터 훑는다.
_fresh_boot = True
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
        # [2026-08-05] 프록시(_mounts) 경유 금지 — 그 프록시는 **크림 API 전용**(119.206.x)이라
        # 슬랙으로 나가면 조용히 삼켜진다. 실측: 컨테이너에서 직접 POST 하면 200 'ok' 인데
        # 사이클 요약만 안 나갔고, except 로그조차 안 찍혔다(예외가 아니라 무응답).
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.post(_SLACK_WEBHOOK, json={"text": msg})
        # [2026-08-03] 응답을 버려서 웹훅 만료·payload 거부가 로그 한 줄 없이 사라졌다.
        # 슬랙은 예외를 던지지 않고 non-200 + 본문(no_service / invalid_payload)으로만
        # 알려주므로, 코드를 확인하지 않으면 '알림이 조용히 끊긴' 상태를 영영 모른다.
        if r.status_code != 200:
            logger.warning(
                "[크림통합] 슬랙 발송 거부 HTTP %s: %s (본문 %d자)",
                r.status_code,
                r.text[:120],
                len(msg),
            )
    except Exception as exc:
        logger.warning("[크림통합] 슬랙 발송 실패(무시): %s", exc)


# 매수추천/원가오염 감시 상태 — {kid: {"h": 고점엔, "a": 매수알림함, "sa": 오염알림함}}
_SET_WATCH = "kream_snkr_watch"

# ── 급락 가드 [로컬 _kream_ask_adjust._guard_jpy 이식] ──────────────────────
# 사고: 스니덩 최저 1건이 일시 급락(¥16,000→¥11,300)하면 원가·최소가가 붕괴해
# 저가 입찰·체결(652078 PSA10: 정상175,000 → 129,000 체결, 손실46,000)이 난다.
# 대응: 직전 사이클 원가 대비 30%↓ 급락이면 1사이클 보류(직전가로 계산=인하 방지).
# 다음 사이클에도 낮으면 진짜 하락으로 수용. 상태는 samba_settings 에 유지.
_SET_GUARD = "kream_price_guard"

# ── 실순위(live_rank) 사전 조회 [2026-08-03] ────────────────────────────────
# 공식 목록 API(/asks)는 live_rank 를 항상 null 로 준다. 단건(/asks/{id})만 실값을 준다.
# 그동안 순위를 '조정한 뒤' PATCH 응답으로만 알 수 있어, 이미 밀려 있는 입찰을 발견하지
# 못했다(표본 40건 중 10건이 2등 이하였다). 조정 전에 순위를 먼저 확인한다.
# 비용 실측: 건당 100ms, 동시 16 기준 1,000건에 약 6초.
_g_live_rank: dict = {}  # ask_id -> live_rank(int). 사이클 내에서만 유효
_RANK_CONCURRENCY = int(os.environ.get("KREAM_RANK_CONCURRENCY") or 16)
# [2026-08-04] 실순위 단건조회 상한 — 0 이면 조회 자체를 건너뛴다.
# [2026-08-13] 기본값 0 → 12,000. 위 주석의 "lowest_* 로 정확히 판정된다"는 **틀렸다**.
# 크림은 같은 가격이면 먼저 넣은 쪽이 1등이라, 동가 경합에서는 내 가격 == lowest 인데도
# 2등이다. lowest_* 에 내 입찰이 섞여 있어 시세만으론 이걸 구분할 방법이 아예 없다.
#   실측(판매자센터): 555088-103|300 판매입찰 260,000원이 2건 — 내 것은 '일반 입찰 순번 2'.
#   그런데 코드는 cur <= market_low 라 1등으로 보고 그대로 유지했다.
# 조회를 꺼둔 탓에 '1순위 27,876' 집계도 동가 2등을 전부 1등으로 세고 있었다.
# 12,000/사이클이면 라이브 입찰 3만 건을 로테이션 3사이클에 전량 커버한다.
_RANK_SCAN_MAX = int(os.environ.get("KREAM_RANK_SCAN_MAX") or 12000)
_rank_scan_offset = 0


async def _fetch_live_ranks(h: dict, ask_ids: list) -> dict:
    """ask_id 목록의 실순위를 병렬 조회. 실패분은 결과에서 빠진다(=판단에 안 씀)."""
    out: dict = {}
    if not ask_ids:
        return out
    sem = asyncio.Semaphore(_RANK_CONCURRENCY)

    async def _one(aid):
        async with sem:
            try:
                r = await _rq(
                    "GET", f"{KREAM_OPENAPI_BASE}/asks/{aid}", headers=h, tries=2
                )
                if r.status_code == 200:
                    v = (r.json() or {}).get("live_rank")
                    if v is not None:
                        out[str(aid)] = int(v)
            except Exception:
                pass

    # [2026-08-13] 12,000건을 gather 로 한꺼번에 띄우면 세마포어가 동시 실행을 16으로
    # 묶어도 **대기 코루틴 수천 개**가 이벤트루프에 얹힌다.
    #   실측: 활성 task 2,207 / [loop-lag] 이벤트루프 1.25초 블로킹 반복.
    # 청크로 끊어 대기열 자체를 작게 유지한다(동시 실행 수는 세마포어가 그대로 결정).
    _CH = 500
    for _i in range(0, len(ask_ids), _CH):
        await asyncio.gather(*[_one(a) for a in ask_ids[_i : _i + _CH]])
    return out


async def _load_live_ranks(
    h: dict, asks: list, priority_ids: list | None = None
) -> None:
    """사이클 시작 시 실순위 적재 — 우선분(갱신 대상) 전량 + 나머지는 로테이션."""
    global _rank_scan_offset, _g_live_rank
    _g_live_rank = {}
    ids_all = [str(a.get("id")) for a in asks if a.get("id")]
    pri = [str(x) for x in (priority_ids or []) if x]
    pri_set = set(pri)
    rest = [x for x in ids_all if x not in pri_set]
    room = max(0, _RANK_SCAN_MAX - len(pri))
    if rest and room:
        # [2026-08-13] 오프셋을 **슬라이스한 뒤** 길이(=room)로 나누고 있었다.
        # (st + room) % room == st % room 이라 오프셋이 room 범위에 갇혀
        # 매 사이클 같은 앞부분만 다시 스캔했다 — 로테이션이 전량을 못 돌았다.
        # 원본 길이로 나눠야 다음 사이클이 이어서 스캔한다.
        _total = len(rest)
        st = _rank_scan_offset % _total
        rest = (rest[st:] + rest[:st])[:room]
        _rank_scan_offset = (st + room) % _total
    else:
        rest = []
    target = pri + rest
    if not target:
        # [2026-08-07] 조용히 건너뛰던 자리. KREAM_RANK_SCAN_MAX 미설정(기본 0) + 우선분
        # 미지정이면 target 이 비어 실순위를 **한 건도 안 받는다**. 그러면 판정은 전부
        # cur <= market_low 추정으로 떨어지는데, market_low 에는 내 입찰이 섞여 있어
        # 동가 경합에서 내가 몇 등인지 알 수 없다. 꺼져 있다는 사실이라도 남긴다.
        logger.info(
            "[크림통합] 실순위 조회 건너뜀 — 대상0건 (KREAM_RANK_SCAN_MAX=%d). "
            "순위는 시세 추정으로 판정",
            _RANK_SCAN_MAX,
        )
        return
    _t = _time_mod.time()
    _g_live_rank = await _fetch_live_ranks(h, target)
    _r2 = sum(1 for v in _g_live_rank.values() if v >= 2)
    logger.info(
        "[크림통합] 실순위 조회 %d건(우선%d+스캔%d) %.0f초 — 2등이하 %d건",
        len(_g_live_rank),
        len(pri),
        len(rest),
        _time_mod.time() - _t,
        _r2,
    )


_g_price_guard: dict = {}
# 옵션 매칭 실패 수집 [2026-08-05] — "kid|DB옵션명" → 크림 옵션명 목록.
_g_optmiss: dict = {}
# 리스톡 스킵 사유별 샘플 [2026-08-05] — 사유코드 → [(kid, 옵션, 부가정보)].
# 카운터만 있어 "왜 안 붙었나"를 상품 하나씩 파봐야 알 수 있었다. 사유마다 실제
# 건을 남겨 다음 사이클에 바로 추적한다. 사유당 최대 8건(로그 폭주 방지).
_g_skip_samples: dict = {}


def _skip_note(reason: str, kid: str, opt: str = "", extra: str = "") -> None:
    """리스톡 스킵 사유 샘플 적재 — 사유당 8건까지."""
    try:
        lst = _g_skip_samples.setdefault(reason, [])
        if len(lst) < 8:
            lst.append(f"{kid}|{opt}{(' ' + extra) if extra else ''}")
    except Exception:
        pass


# [2026-08-05] 상품 단위 추적 — "왜 이 상품이 등록 안 되냐"를 추측 없이 답하기 위해.
# KREAM_TRACE_KIDS="14334,177955" 로 지정하면 그 상품이 지나가는 모든 분기를 남긴다.
# 전량에 걸면 로그가 폭발하므로 지정한 kid 만 찍는다.
_TRACE_KIDS: set = {
    x.strip()
    for x in (os.environ.get("KREAM_TRACE_KIDS") or "").split(",")
    if x.strip()
}
# 사유별 소멸 집계 — 등록 후보에서 빠진 모든 경로가 여기 누적된다(사이클마다 리셋).
_g_drop: dict[str, int] = {}
# 이번 사이클에 **판정까지 못 간** kid — 스캔목록에서 빼서 다음 사이클에 다시 본다.
_g_unjudged: set = set()


def _trace(kid: str, opt: str, msg: str) -> None:
    """지정 상품의 분기 통과 기록."""
    if kid and str(kid) in _TRACE_KIDS:
        logger.info("[크림추적] %s|%s %s", kid, opt, msg)


def _drop(reason: str, kid: str = "", opt: str = "", extra: str = "") -> None:
    """등록 후보에서 빠진 사유 기록 — 집계 + 샘플 + 추적.

    조용한 continue/return 이 '이유 모를 미등록'을 만들었다. 빠지는 길목마다 부른다.
    """
    _g_drop[reason] = _g_drop.get(reason, 0) + 1
    _skip_note(reason, kid, opt, extra)
    _trace(kid, opt, f"제외: {reason}{(' ' + extra) if extra else ''}")


def _fail_kind(reason: str) -> str:
    """등록 실패 응답을 사유 묶음으로 분류 — 사이클 요약에서 원인별로 보이게. [2026-08-06]"""
    r = str(reason or "")
    if "고시" in r or "announcement" in r:
        return "고시미등록"
    if "500" in r:
        return "크림500"
    if "천원" in r or "1000" in r:
        return "천원단위"
    if "입찰" in r and ("제한" in r or "불가" in r):
        return "입찰제한"
    if "옵션" in r or "상품 정보가 변경" in r:
        return "옵션불일치"
    if "timeout" in r.lower() or "timed out" in r.lower():
        return "타임아웃"
    return (r[:24] or "기타") if r else "기타"


def _guard_jpy(kid: str, opt: str, cur_jpy: int) -> int:
    """급락이면 직전가 반환(1사이클 보류), 아니면 현재가 그대로. 반환값이 원가 계산 기준."""
    try:
        cur = int(cur_jpy or 0)
    except (TypeError, ValueError):
        return cur_jpy
    if cur <= 0:
        return cur_jpy
    k = f"{kid}|{opt}"
    st = _g_price_guard.get(k) or {}
    prev = int(st.get("p") or 0)
    hold = int(st.get("hold") or 0)
    eff = cur
    if prev > 0 and cur < prev * 0.7:
        if hold < 1:
            eff = prev  # 1회 보류 — 이번 사이클은 직전가로 계산(인하 방지)
            hold = 1
            _emit_autotune_log(
                "KREAM",
                kid,
                f"급락보류 {opt} ¥{prev:,}→¥{cur:,} "
                f"(-{int((1 - cur / prev) * 100)}%) 일회성 의심, 가격유지",
            )
        else:
            hold = 0  # 2사이클 연속 저가 → 진짜 하락 수용
    else:
        hold = 0
    _g_price_guard[k] = {"p": eff, "hold": hold}
    return eff


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


async def _brand_reg_rates(limit: int = 14) -> tuple[str, str]:
    """브랜드별 '입찰상품수/재고매칭상품수' 두 줄. [2026-08-13 상품 단위로 전환]

    종전에는 '옵션' 단위 비율(퍼센트)만 찍어서, 브랜드가 통째로 입찰 0건이어도
    다른 브랜드 퍼센트에 묻혀 안 보였다. 실측에서 Supreme(재고 56)·Mihara(52)·
    Play CDG(73) 가 전부 입찰 0인 게 이렇게 가려져 있었다. 그래서
      1) 분자/분모를 상품 수로 그대로 노출하고(브랜드별 규모를 눈으로 비교),
      2) 재고가 있는데 입찰이 0인 브랜드는 따로 경고 줄로 뽑는다.

    분모는 '재고 있는 매칭 상품'이다. 재고 0이면 애초에 입찰 대상이 아니라
    전체 매칭수를 분모로 쓰면 등록률이 실제보다 낮게 보인다(구찌 1,899 vs 302).

    반환: (등록률 줄, 입찰0 브랜드 경고 줄) — 각각 비면 "".
    """
    try:
        async with get_read_session() as s:
            rows = (
                await s.execute(
                    _text(
                        "WITH m AS ("
                        "  SELECT cp.id, TRIM(cp.brand) br,"
                        "         cp.resell_matches->'kream'->>'product_id' kid"
                        "  FROM samba_collected_product cp"
                        "  WHERE cp.source_site IN ('SNKRDUNK','ONITSUKA')"
                        "    AND COALESCE(cp.resell_matches->'kream'->>'product_id','')<>''"
                        "    AND (cp.resell_matches->'kream'->>'verified')='true'"
                        "    AND jsonb_typeof(cp.options::jsonb)='array'"
                        "    AND EXISTS (SELECT 1"
                        "        FROM jsonb_array_elements(cp.options::jsonb) x"
                        "        WHERE COALESCE((x->>'stock')::int,0) > 0"
                        "          AND COALESCE((x->>'price')::int,0)"
                        "              BETWEEN 5000 AND :maxc))"
                        "SELECT m.br, COUNT(*) tot,"
                        "       COUNT(*) FILTER (WHERE a.product_id IS NOT NULL) reg "
                        "FROM m LEFT JOIN (SELECT DISTINCT product_id FROM kream_live_asks) a"
                        "  ON a.product_id = m.kid "
                        "GROUP BY m.br HAVING COUNT(*) >= 10 ORDER BY 2 DESC LIMIT :n"
                    ),
                    # 원가 상한은 정책값(kreamMaxCostJpy). 25만엔 하드코딩이면 정책이
                    # 35만이어도 25만~35만 구간이 집계에서 빠져 등록률이 왜곡된다.
                    {"n": limit, "maxc": int(POLICY["max_cost_jpy"])},
                )
            ).all()
        if not rows:
            return "", ""
        live = [(str(r[0]), int(r[1]), int(r[2])) for r in rows]
        head = " · ".join(
            f"{br} {reg:,}/{tot:,}({round(100.0 * reg / max(1, tot), 1)}%)"
            for br, tot, reg in live
        )
        zero = [f"{br} 0/{tot:,}" for br, tot, reg in live if reg == 0]
        return head, (" · ".join(zero) if zero else "")
    except Exception as exc:
        logger.info("[크림통합] 브랜드 등록률 집계 실패(무시): %s", str(exc)[:60])
        return "", ""


async def _count_cat1_verified_unreg() -> int:
    """검수 카테고리1(재고O+매칭) 중 '매칭확인(verified)'됐으나 크림 미등록(입찰 없음)인 상품수.
    자동입찰 누락 감시용 — 확인 끝난 재고상품이 아직 크림에 안 걸린 것. 실패 시 -1.
    정의는 proxy/kream.py 검수목록(get_snkrdunk_compare_all)의 cat/verified/registered 와 동일."""
    sql = _text(
        """
        SELECT COUNT(*) FROM samba_collected_product p
        WHERE p.source_site IN ('SNKRDUNK','ONITSUKA')
          AND COALESCE(p.resell_matches->'kream'->>'verified','') = 'true'
          AND (
            COALESCE(p.resell_matches->'kream'->>'product_id','') <> ''
            OR jsonb_array_length(
                 COALESCE(p.resell_matches->'kream_candidates','[]'::jsonb)) > 0
          )
          AND (
            COALESCE((SELECT NULLIF(o->>'stock','')::int
                      FROM jsonb_array_elements(p.options::jsonb) o
                      WHERE REPLACE(o->>'name',' ','')='PSA10' LIMIT 1),0) > 0
            OR COALESCE((SELECT NULLIF(o->>'stock','')::int
                      FROM jsonb_array_elements(p.options::jsonb) o
                      WHERE REPLACE(o->>'name',' ','')='PSA9' LIMIT 1),0) > 0
            OR (p.extra_data->>'snkr_type' IN ('sneaker','apparel','watch')
                AND COALESCE((SELECT SUM(NULLIF(o->>'stock','')::int)
                      FROM jsonb_array_elements(p.options::jsonb) o),0) > 0)
          )
          AND NOT (
            COALESCE(p.resell_matches->'kream'->>'product_id','') <> ''
            AND p.resell_matches->'kream'->>'product_id'
                IN (SELECT product_id FROM kream_live_asks)
          )
        """
    )
    try:
        async with get_read_session() as s:
            return int((await s.execute(sql)).scalar() or 0)
    except Exception as exc:
        logger.warning("[크림통합] cat1 확인·미등록 집계 실패(무시): %s", exc)
        return -1


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
        async with httpx.AsyncClient(mounts=_mounts(), timeout=25) as cli:
            for a in orphans:
                # [2026-08-05] kid/opt 를 반드시 넘긴다 — 안 넘기면 "우리가 지운 것"으로
                # 기록되지 않아 다음 사이클이 판매로 오인하고 6시간 재등록을 막는다.
                if a.get("id") and await _exec_delete_ask(
                    cli, h, a.get("id"), a.get("product_id"), a.get("option")
                ):
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
    # 조정 데드밴드(원) — 목표가와 현재가 차이가 이 금액 미만이면 조정 생략.
    # 실시간 원가/시세의 미세변동이 매 사이클 수백 건의 헛조정으로 번지는 것 차단.
    # 단 '마진 하한 미달(현재가 < 최소가)' 은 손실 방지라 데드밴드와 무관하게 항상 조정.
    "adjust_deadband_krw": 2000,
    # ── 크림 판매수수료(정산 차감분) [2026-08-02] ──
    # 해외배송(박스·카드팩): 기본 1,370원 + 판매가 3.3%  ※3.3% 는 3%+VAT 가 이미 포함된 값
    "overseas_base_fee": 1370,
    "overseas_fee_rate": 3.3,
    # 신발/의류/시계: (기본 2,500원 + 판매가 5.6%) × VAT 1.1 = 2,750 + 6.16%
    # 요율은 판매등급별(L5 5.50 / L4 5.60 / L3 5.70 / L2 5.85 / L1 6.00) — 정책에서 주입
    "item_fee_base": 2500,
    "item_fee_rate": 5.6,
    "item_fee_vat": 10,
    # PSA 낱장 카드는 수수료 무료 → 별도 값 없음
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
                        "adjust_deadband_krw": k.get(
                            "kreamAdjustDeadbandKrw", POLICY["adjust_deadband_krw"]
                        ),
                        # 판매수수료 — 정책관리 값 우선, 없으면 기본값 [2026-08-02]
                        "overseas_base_fee": k.get(
                            "kreamOverseasBaseFee", POLICY["overseas_base_fee"]
                        ),
                        "overseas_fee_rate": k.get(
                            "kreamOverseasFeeRate", POLICY["overseas_fee_rate"]
                        ),
                        "item_fee_base": k.get(
                            "kreamItemFeeBase", POLICY["item_fee_base"]
                        ),
                        # 등급율은 판매등급에서 도출(margin-policy 엔드포인트와 동일 표)
                        "item_fee_rate": {
                            5: 5.50,
                            4: 5.60,
                            3: 5.70,
                            2: 5.85,
                            1: 6.00,
                        }.get(int(k.get("kreamSellerLevel", 4) or 4), 5.60),
                        "item_fee_vat": k.get(
                            "kreamItemFeeVat", POLICY["item_fee_vat"]
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
    idx: int,
    total: int,
    price_cnt: int,
    del_cnt: int,
    processed: int = 0,
    cycle_sec: float = 0.0,
    stock_cnt: int = 0,
) -> None:
    """크림 사이클 진행상태를 DB 기록 → api /autotune/active-cycles 가 읽어 SNKRDUNK 활성 표시.
    processed/cycle_sec 로 처리속도(avg_sec_per_item) 계산 지원.
    stock_cnt = 실제 재고변화 건수(리스톡+삭제) — 재배포 리셋 방지 위해 cycle_count 는 DB 복원."""
    global _kream_cycle_count, _kream_started_at
    from datetime import datetime, timezone

    # 재시작 직후(인메모리 0)면 DB 에서 이전 사이클#·시작시각 복원 — 재배포마다 1로 리셋돼
    # 활성사이클이 '멈춘 것처럼' 보이던 문제.
    if _kream_cycle_count == 0:
        try:
            _prev = await _load_setting_map("kream_cycle_status")
            _kream_cycle_count = int(_prev.get("cycle_count") or 0)
            if _kream_started_at is None and _prev.get("started_at"):
                _kream_started_at = str(_prev.get("started_at"))
        except Exception:
            pass
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
            "stock_count": int(stock_cnt),  # 실제 재고변화(리스톡+삭제)
            "cycle_count": _kream_cycle_count,
            "processed": int(processed),  # 이번 사이클 처리 상품 수
            "cycle_sec": round(float(cycle_sec), 1),  # 이번 사이클 소요(초)
            "avg_sec": round(cycle_sec / processed, 3) if processed > 0 else 0,
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
    """크림 오토튠 로그 1줄 적재. 라벨은 **소싱처(SNKRDUNK)** 로 통일 — 활성사이클/소싱처 필터와
    일치시키기 위함(크림은 판매처라 [KREAM] 이면 소싱처 그룹서 이탈). 포맷=오토튠 UI 동일.
    '실패0' 처럼 0건인데 프론트가 '실패' 문자열로 빨간 오류처리하던 것 방지 — 호출부에서
    실패건은 >0 일 때만 붙인다."""
    try:
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        ts = (now + timedelta(hours=9)).strftime("%H:%M:%S")
        _pending_logs.append(
            {
                "site": "SNKRDUNK",  # 소싱처 기준 라벨 통일
                "product_id": str(product_id or ""),
                "msg": f"[{ts}] [SNKRDUNK] {msg}",
                "level": level,
                "device_id": "",  # 빈 device_id = 글로벌 → 어느 PC 필터에서도 노출
            }
        )
    except Exception:
        pass


def _fail_tag(n: int) -> str:
    """실패건 태그 — 0 이면 빈 문자열(프론트가 '실패' 문자열을 빨간 오류로 처리하는 것 회피)."""
    return f" 실패{n:,}" if n else ""


async def _write_live_asks_snapshot(asks: list) -> None:
    """현재 live 입찰 스냅샷을 kream_live_asks 에 되쓴다 — 검수페이지 '등록여부' 실시간 반영.
    로컬봇(_kream_ask_adjust)이 매 사이클 하던 것. 백엔드 이관 후 끊겨 07-22 동결 →
    이후 입찰분이 전부 '미등록' 오분류되던 버그. TRUNCATE+INSERT 를 한 트랜잭션으로
    (원자적) — 중간 실패 시 rollback 돼 기존 스냅샷 보존(전부 미등록 되는 사고 방지)."""
    if not asks:
        return
    seen: set = set()
    rows: list = []
    for a in asks:
        kid = str(a.get("product_id") or "")
        opt = str(a.get("option") or "")
        if not kid or (kid, opt) in seen:
            continue
        seen.add((kid, opt))
        rows.append({"k": kid, "o": opt, "p": int(a.get("price") or 0)})
    if not rows:
        return
    try:
        from backend.db.orm import get_write_session

        async with get_write_session() as s:
            await s.execute(_text("TRUNCATE kream_live_asks"))
            await s.execute(
                _text(
                    "INSERT INTO kream_live_asks (product_id, option, price, updated_at) "
                    "VALUES (:k, :o, :p, NOW())"
                ),
                rows,
            )
            await s.commit()
    except Exception as exc:
        logger.warning("[크림통합] kream_live_asks 스냅샷 실패(무시): %s", exc)


async def _write_back_db_options(updates: list) -> None:
    """실시간 snkr 원가/재고를 samba_collected_product.options 에 되쓴다.
    카드는 마켓 미등록이라 메인 오토튠이 갱신 안 함 → 전수스캔 정지 후 db_opts 가 낡음.
    검수페이지/데일리리포트/즉시수익 계산 정확도 + 다음 사이클 급락가드 직전가 정확도용.
    옵션/원가만 갱신(가격결정엔 매 사이클 실시간값을 직접 쓰므로 여기 write 는 부수효과)."""
    if not updates:
        return
    try:
        from backend.db.orm import get_write_session

        async with get_write_session() as s:
            for snkr_id, opts, cost in updates:
                await s.execute(
                    _text(
                        "UPDATE samba_collected_product "
                        "SET options = CAST(:opt AS jsonb), "
                        # 소싱품절(cost0)이면 기존 원가 보존 — 재고/확인시각만 갱신
                        "cost = CASE WHEN :cost > 0 THEN :cost ELSE cost END, "
                        "updated_at = NOW() "
                        "WHERE source_site='SNKRDUNK' AND site_product_id = :sid"
                    ),
                    {
                        "opt": json.dumps(opts, ensure_ascii=False),
                        "cost": float(cost),
                        "sid": str(snkr_id),
                    },
                )
            await s.commit()
    except Exception as exc:
        logger.warning("[크림통합] DB 원가/재고 되쓰기 실패(무시): %s", exc)


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
_hb_clamp = {"used": 0, "cap": 10**9}  # [2026-08-05] 상한 제거
# (kid, opt) → 마진 하한. 순위교정 시 이 아래로는 절대 안 내린다.
_floor_map: dict = {}
# 순위교정(rank>=2 → 1,000원 인하) 사이클 상한
_rank_fix = {"used": 0, "cap": 10**9}  # [2026-08-05] 상한 제거


async def _fetch_highest_bid(cli, h, pid: str, opt: str) -> int:
    """옵션별 최고구매입찰가 — 크림 판매입찰가는 이 값 이상이어야 등록/수정된다."""
    try:
        r = await _rq("GET", f"{KREAM_OPENAPI_BASE}/products/{pid}", headers=h)
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
    # ── 출력단 마진 하한 최종 가드 [이중방어] ──
    # 입력단 급락가드를 통과하더라도(직전가 없음·완만한 하락 등) 최소가 미만 값은 절대
    # 전송 금지. 원가가 뭐든 마진 하한(_floor_map) 이상만 나가게 강제한다.
    # 652078/649924 저마진 체결(8~9%, 정책 14%) 재발 원천 차단.
    _floor = int(_floor_map.get((str(pid), str(opt)), 0) or 0)
    if _floor > 0 and int(target) < _floor:
        _note_fail(f"마진하한미달 차단: 목표 {int(target):,} < 최소 {_floor:,}")
        logger.warning(
            "[크림통합] 마진하한 차단 %s %s: 목표 %s < 최소 %s",
            pid,
            opt,
            f"{int(target):,}",
            f"{_floor:,}",
        )
        return "fail", None
    try:
        # 보관 전환 신청(is_keep_on_deferred) 명시 — 스펙상 미입력 시 기존값 유지라
        # 매 수정마다 실어야 보관판매 유지(안 실으면 자동입찰이 신청 놓쳐 false 방치).
        # 이후 순위교정 PATCH 는 가격만 보내도 기존 keep 유지됨.
        _pkey = f"{pid}|{opt}"
        _pbody = {"price": int(target)}
        if _pkey not in _keep_impossible:
            _pbody["is_keep_on_deferred"] = True
        r = await _rq(
            "PATCH", f"{KREAM_OPENAPI_BASE}/asks/{ask_id}", headers=h, json=_pbody
        )
        # 보관 불가 상품(400 '보관 신청이 불가능') → keep 빼고 재시도(갱신 자체는 성공)
        if (
            r.status_code not in (200, 201)
            and "is_keep_on_deferred" in _pbody
            and "보관" in (r.text or "")
        ):
            _keep_impossible.add(_pkey)
            _pbody.pop("is_keep_on_deferred")
            r = await _rq(
                "PATCH", f"{KREAM_OPENAPI_BASE}/asks/{ask_id}", headers=h, json=_pbody
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
                hb = int(hb) // 1000 * 1000
                # ── 마진 하한 가드 [저마진 체결 원천차단·2026-07-25] ──
                # 입찰제한 보정도 최소가(_floor) 밑으론 절대 안 내린다. hb < 최소가면
                # 재입찰 포기(쿨다운) — 마진 하한 밑 판매 방지. 651557 PSA10 5.7% 체결 사고.
                if hb > 0 and _floor > 0 and hb < _floor:
                    _note_fail(
                        f"입찰제한-마진하한 차단: 최고입찰가 {hb:,} < 최소 {_floor:,}"
                    )
                    _g_limit_cd[f"{pid}|{opt}"] = _now_ts()
                    return "fail", None
                if hb > 0 and hb != int(target):
                    _hb_clamp["used"] += 1
                    r2 = await _rq(
                        "PATCH",
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
                r3 = await _rq(
                    "PATCH",
                    f"{KREAM_OPENAPI_BASE}/asks/{ask_id}",
                    headers=h,
                    json={"price": _new},
                )
                if r3.status_code in (200, 201):
                    return "ok", (r3.json() or {}).get("live_rank")
        if is_nocomp and rank is not None and rank != 1:
            # [2026-08-03] 원래 가격으로 그냥 되돌리면 다음 사이클에 똑같이 올렸다 밀리는
            # 왕복이 무한 반복된다(884440: 71,000→76,000→복귀를 매 사이클).
            # 인상된 지금이 경쟁가를 알 수 있는 유일한 순간이다 — 내가 최저일 때 lowest_*
            # 는 내 가격만 되비추지만, 내가 위로 올라간 상태에서는 '남의 가격'이 드러난다.
            # 그 값 바로 아래로 잡아 1등을 되찾는다(마진 하한 _floor 는 절대 안 깬다).
            _back = int(cur)
            try:
                _pr = await _rq(
                    "GET", f"{KREAM_OPENAPI_BASE}/products/{pid}", headers=h
                )
                _want = str(opt).replace(" ", "")
                _po = next(
                    (
                        _o
                        for _o in ((_pr.json() or {}).get("options") or [])
                        if str(_o.get("name") or "").replace(" ", "") == _want
                    ),
                    None,
                )
                if _po:
                    _rival = int(_po.get("lowest_normal_price") or 0) or int(
                        _po.get("lowest_overseas_price") or 0
                    )
                    # 내 인상가보다 낮게 잡히는 값 = 경쟁자 실가격
                    if 0 < _rival < int(target):
                        _cand = _rival - 1000
                        if _cand > 0 and (_floor <= 0 or _cand >= _floor):
                            _back = _cand
            except Exception as _e:
                logger.info(
                    "[크림통합] 경쟁가 재조회 실패(원복 진행) %s %s: %s",
                    pid,
                    opt,
                    str(_e)[:60],
                )
            await _rq(
                "PATCH",
                f"{KREAM_OPENAPI_BASE}/asks/{ask_id}",
                headers=h,
                json={"price": _back},
            )
            await record_nocomp_cooldown(pid, opt)
            if _back != int(cur):
                logger.info(
                    "[크림통합] 경쟁가 추종 %s %s: %s→%s (인상 %s 밀림, rank=%s)",
                    pid,
                    opt,
                    f"{int(cur):,}",
                    f"{_back:,}",
                    f"{int(target):,}",
                    rank,
                )
                return "ok", rank
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


def gross_up_kream_fee(net: float, fee_kind: str | None) -> float:
    """정산 net 을 받으려면 얼마에 팔아야 하는지(수수료 역산) [2026-08-02].

    크림 판매수수료(부가세 10% 포함 실효):
      · None/"card" : PSA 낱장 = 무료 → 그대로
      · "overseas"  : 해외배송(박스·카드팩) = 1,370 + 판매가×3.3%
                      ※ 3.3% 는 3% + VAT 가 이미 반영된 값(요율에 포함)
      · "item"      : 신발/의류/시계 = (2,500 + 판매가×5.6%) × 1.1
                      = 2,750 + 판매가×6.16%
    fee_kind 미지정이면 수수료 미반영(기존 동작 그대로) — 분류가 모호한 호출부 보호.
    """
    if fee_kind == "overseas":
        fixed = float(POLICY["overseas_base_fee"])
        rate_pct = float(POLICY["overseas_fee_rate"])
    elif fee_kind == "item":
        vat = 1 + float(POLICY["item_fee_vat"]) / 100
        fixed = float(POLICY["item_fee_base"]) * vat
        rate_pct = float(POLICY["item_fee_rate"]) * vat
    else:
        return net
    if rate_pct >= 100:
        return net
    return (net + fixed) / (1 - rate_pct / 100)


def calc_min_price(
    price_jpy: float,
    rate: float,
    is_box: bool = False,
    is_card: bool = True,
    surcharge_rate: float | None = None,
    fee_kind: str | None = None,
) -> int:
    base = calc_base(price_jpy, rate, is_box, is_card, surcharge_rate)
    margin = max(
        float(POLICY["min_margin_amount"]),
        base * POLICY["competitive_margin_rate"] / 100,
    )
    # 크림 판매수수료는 정산에서 차감되므로, 목표마진을 실제로 남기려면 등록가에 얹어야 한다.
    # (기존엔 미반영이라 순마진이 수수료만큼 깎여 있었음)
    gross = gross_up_kream_fee(base + margin, fee_kind)
    return int((gross + 999) // 1000 * 1000)


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
    return await _fetch_asks_by_status(h, "live")


async def _rq(method: str, url: str, *, headers=None, params=None, json=None, tries=4):
    """터널 경유 요청 — 응답이 11초 안 오면 그 요청을 버리고(취소불가 TLS stuck) 새 연결로 재시도.
    [2026-08-01] 크림/스니덩크 호출 하나가 anyio TLS 락에서 영구 매달려(httpx timeout·cancel 무효)
    사이클 전체가 멈추던 것 해소. 매번 새 연결(keep-alive off)."""

    async def _do():
        async with httpx.AsyncClient(
            mounts=_mounts(),
            timeout=10,
            limits=httpx.Limits(max_keepalive_connections=0),
        ) as c:
            return await c.request(
                method, url, headers=headers, params=params, json=json
            )

    for attempt in range(tries):
        task = asyncio.ensure_future(_do())
        done, _p = await asyncio.wait({task}, timeout=11)
        if task in done:
            exc = task.exception()
            if exc is None:
                return task.result()
            if attempt >= tries - 1:
                raise exc
            await asyncio.sleep(0.3)
            continue
        task.cancel()
        task.add_done_callback(lambda t: t.cancelled() or t.exception())
    raise TimeoutError(f"{method} stuck: {url[:60]}")


async def _fetch_asks_by_status(h: dict, status: str) -> list[dict]:
    """상태별 내 입찰 전량(공식 OpenAPI). 읽기 전용.
    [2026-08-01] 6천건=120페이지 순차면 stuck 하나에 사이클 정지 → page1로 총수 파악 후
    나머지 8개씩 동시 조회(~23초), 각 페이지는 _rq 로 stuck-버리고-재시도."""

    async def _page(p: int) -> dict:
        r = await _rq(
            "GET",
            f"{KREAM_OPENAPI_BASE}/asks",
            headers=h,
            params={"status": status, "page": p, "per_page": _PER_PAGE},
        )
        r.raise_for_status()
        return r.json()

    d1 = await _page(1)
    total = int(d1.get("total") or 0)
    npages = (total + _PER_PAGE - 1) // _PER_PAGE
    if npages <= 1 or not (d1.get("items") or []):
        return list(d1.get("items") or [])
    # [2026-08-02] live 입찰 5,600건+ 로 늘어 동시성 8로는 사이클 완주 불가(슬랙 정지).
    # 스니덩크 동시요청 안전 실증(단일 0.2s, 동시10 0.2s) → 상향. 환경변수로 조절.
    sem = asyncio.Semaphore(int(os.environ.get("KREAM_CARD_CONCURRENCY") or 24))

    async def _one(p: int) -> dict:
        async with sem:
            return await _page(p)

    # [2026-08-06] 페이징 결과를 **ask id 로 모으고 total 과 대조한다.**
    # 종전엔 페이지 응답을 그대로 이어붙이고 검증이 없었다. 511 페이지를 넘기는 동안
    # 등록·삭제로 목록이 밀리면 어떤 항목은 두 페이지에 걸쳐 들어오고, 어떤 항목은
    # 페이지 경계 밖으로 밀려 아예 안 잡힌다.
    #   실측(2026-08-06 01:55 KST, live total 24,154):
    #     수집 행수 24,200 (375행 중복) / 고유 23,825 → **329건 누락**
    # 누락된 입찰은 갱신 대상에서 통째로 빠지고, 리스톡은 '입찰 없음'으로 오인한다.
    # 고유 수가 total 에 못 미치면 부족분이 채워질 때까지 다시 훑는다(최대 2회 추가).
    seen: dict = {}

    def _collect(items) -> None:
        for _i, a in enumerate(items or []):
            _aid = str(a.get("id") or "")
            seen[_aid or f"_noid_{len(seen)}_{_i}"] = a

    _collect(d1.get("items"))
    for _round in range(3):
        pages = range(2, npages + 1) if _round == 0 else range(1, npages + 1)
        for d in await asyncio.gather(*[_one(p) for p in pages]):
            _collect(d.get("items"))
        if total <= 0 or len(seen) >= total:
            break
        _miss = total - len(seen)
        if _miss <= max(1, int(total * 0.001)):  # 0.1% 이하 = 조회 중 정상 변동
            break
        logger.info(
            "[크림] %s 입찰 조회 누락 %d건(수집 %d/%d) — 재조회 %d회차",
            status,
            _miss,
            len(seen),
            total,
            _round + 1,
        )
    return list(seen.values())


# [Step 4] 환율 소스 = 로컬 봇(_kream_ask_adjust get_rate_cached)과 동일 frankfurter로 정렬.
# 실행 전환 시 백엔드/로컬 target 일치 보장. UA 헤더 필수(없으면 301). 마지막 성공값 인메모리 캐시로
# 순간 조회실패 시 폴백 점프 방지. (구 exchange_rate_service 경로는 rates["KRW"] 키 부재로
# 항상 폴백 9.12 반환하던 버그 — frankfurter 직조회로 대체.)
_rate_cache: dict[str, float] = {}


async def _frankfurter_rate(frm: str, to: str, fallback: float) -> float:
    pair = f"{frm}/{to}"
    try:
        async with httpx.AsyncClient(
            mounts=_mounts(), timeout=10, follow_redirects=True
        ) as cli:
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
# [2026-08-03] "터널IP 직접 접근 OK, 프록시 불필요"였으나 **차단됐다**. 터널IP·집IP 모두
# 403 이 되면서 카드 처리가 0건이 되고 시세 추종이 통째로 멈췄다(snkr실패 1,632/사이클).
# → SNKR_PROXY 가 설정돼 있으면 **snkrdunk.com 요청만** 프록시로 우회한다.
# httpx mounts 는 호스트 매칭이라 크림(partner-openapi)은 그대로 직결로 나간다.
# (httpx 0.28 에서 proxies 인자는 제거됨 — mounts + AsyncHTTPTransport(proxy=) 사용)
_SNKR_PROXIES = [
    p.strip() for p in os.environ.get("SNKR_PROXY", "").split(",") if p.strip()
]
# 라운드로빈 인덱스는 **모듈 전역** — AsyncClient 는 단계마다 새로 만들어지므로
# transport 인스턴스에 두면 매번 0번 프록시로 쏠린다.
_snkr_rr = itertools.count()


class _RoundRobinProxyTransport(httpx.AsyncBaseTransport):
    """요청마다 프록시를 번갈아 쓰는 transport.

    [2026-08-03] 프록시 1개만 물렸더니 신발 시세조회(6,753건)가 6~7분 → 16분+ 로
    늘어 사이클이 완주하지 못했다. 단건 응답은 0.29초로 멀쩡했으니 지연이 아니라
    **동시성 병목**이다(KREAM_SHOE_FETCH_CONCURRENCY=30 이 프록시 1개에 몰림).
    사이클이 느려지면 로테이션 주기가 늘어 입찰 갱신이 밀리고 비1순위가 증가한다
    — 갱신을 살리려던 프록시가 갱신을 죽이는 역설이라 반드시 분산해야 한다.
    """

    def __init__(self, proxies: list[str]):
        self._ts = [httpx.AsyncHTTPTransport(proxy=p) for p in proxies]

    async def handle_async_request(self, request):
        return await self._ts[next(_snkr_rr) % len(self._ts)].handle_async_request(
            request
        )

    async def aclose(self):
        for t in self._ts:
            await t.aclose()


def _mounts():
    """스니덩크 전용 프록시 마운트. 미설정이면 None(기존 직결 동작)."""
    if not _SNKR_PROXIES:
        return None
    tr = _RoundRobinProxyTransport(_SNKR_PROXIES)
    return {"all://snkrdunk.com": tr, "all://*.snkrdunk.com": tr}


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


def _robust_floor(prices_sorted: list[int]) -> int:
    """단일 헐값(오등록/스캠 리스팅) outlier 제거 등급 하한가 [로컬 이식·근본 fix].
    - 5개↑: 중앙값 50% 미만 호가는 outlier 로 버리고 남은 것 중 최저가.
    - 5개 미만(thin market): 버릴 통계근거 부족 → 최저가 그대로.
    이게 근본 fix — 단일 min() 을 믿어 헐값 매물 1개에 원가·최소가가 뚫려 저가체결되던
    사고(652078·831281 등)를 소스에서 차단(모양가드=두더지잡기 종식, 메모리 기록)."""
    if not prices_sorted:
        return 0
    n = len(prices_sorted)
    if n < 5:
        return prices_sorted[0]
    cut = prices_sorted[n // 2] * 0.5  # 중앙값 × 0.5
    for p in prices_sorted:  # 오름차순 — cut 이상 첫 값 = outlier 제거 후 최저
        if p >= cut:
            return p
    return prices_sorted[0]


async def _fetch_snkr_used(cli: httpx.AsyncClient, snkr_id: str) -> dict | None:
    """스니덩크 중고(PSA10/PSA9) 등급별 실시간 하한가(JPY, outlier제거)·재고수.
    page1 실패 시 None(기존 DB값 유지 — 오판 방지). 반환:
    {"PSA 10": {"price": robust하한, "stock": n, "raw_min": 단일최저}, "PSA 9": {...}}.
    단일 min() 이 아니라 _robust_floor 로 헐값 outlier 를 소스에서 걸러 저가체결 근절."""
    cond_prices: dict[str, list[int]] = {}  # 등급별 전체 호가 — robust_floor 용
    page = 1
    while page <= 20:
        try:
            r = await _rq(
                "GET",
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
            cond_prices.setdefault(ckey, []).append(int(p))
        if len(items) < 100:
            break
        page += 1
        await asyncio.sleep(0.2)
    out: dict = {}
    for ckey in ("PSA 10", "PSA 9"):
        prices = sorted(cond_prices.get(ckey) or [])
        out[ckey] = {
            "price": _robust_floor(prices),  # outlier 제거 하한(원가 기준)
            "stock": len(prices),
            "raw_min": prices[0] if prices else 0,  # 참고/로깅용
        }
    return out


async def _html_haslisting(
    cli: httpx.AsyncClient, snkr_id: str, option: str
) -> bool | None:
    """상품 HTML 의 등급별 hasListing 으로 재고 이중검증 [로컬 이식].
    True=재고있음(삭제보류) / False=재고없음(삭제진행) / None=확인불가(안전하게 삭제보류).
    used API 가 순간 0 을 반환해 정상 입찰이 삭제되던 것 방지."""
    o = str(option or "")
    if "10" in o:
        fid = "psa_10"
    elif "9" in o:
        fid = "psa_9"
    else:
        return None
    try:
        r = await cli.get(
            f"https://snkrdunk.com/apparels/{snkr_id}",
            headers={**_SNKR_HEADERS, "Accept": "text/html"},
        )
        if r.status_code != 200:
            return None
        m = re.search(
            r'"filterConditionId":"' + fid + r'"[^}]*"hasListing":(true|false)', r.text
        )
        if m:
            return m.group(1) == "true"
        return False  # 등급 자체 없음 = 재고없음
    except Exception:
        return None


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


async def _fetch_snkr_sizes(cli: httpx.AsyncClient, snkr_id: str) -> dict | None:
    """수량별 최저가 — GET /v1/apparels/{id}/sizes → {수량N: {price, stock}}.
    박스/카드팩의 '해외배송(N개)' 옵션은 낱개×N 이 아니라 N수량 실시세를 써야 한다
    (1パック¥1,610 vs 4パック¥8,499 처럼 규모별 프리미엄/할인 존재). API 실패 시 None."""
    try:
        r = await cli.get(
            f"https://snkrdunk.com/v1/apparels/{snkr_id}/sizes", headers=_SNKR_HEADERS
        )
        if r.status_code != 200:
            return None
        out: dict[int, dict] = {}
        for sp in r.json().get("sizePrices") or []:
            sz = sp.get("size") or {}
            nm = str(sz.get("localizedName") or sz.get("name") or "")
            m = re.search(r"(\d+)", nm)
            if not m:
                continue
            n = int(m.group(1))
            p = int(sp.get("minListingPrice") or 0)
            cnt = int(
                sp.get("listingItemCount") or sp.get("listingCount") or (1 if p else 0)
            )
            out[n] = {"price": p, "stock": cnt}
        return out
    except Exception:
        return None


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


# 크림 갱신 결정 로직 — 갱신·신규등록 전 경로가 이 함수 하나를 거친다.
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
    fee_kind: str | None = None,
    live_rank: int | None = None,
    low_keep: int = 0,
) -> tuple[str, int, bool, bool]:
    """갱신 결정 — 반환 (act, target, adjusting, is_nocomp).
    로컬 _kream_ask_adjust rank1유도+5분기+rank2추종+안전장치 이식.
    is_box=True(박스/카드팩/신발) → 배송비 900엔. surcharge_rate 로 추가마진 분류 지정."""
    is_card = opt.upper().startswith("PSA")
    # 수수료 분류: PSA 낱장=무료 / 해외배송(박스·카드팩)=overseas / 신발·의류=item.
    # 호출부가 fee_kind 를 안 주면 미반영(기존 동작) — floor_map 과 어긋나지 않게 같은 값을 넘긴다.
    min_price = calc_min_price(
        snkr_jpy, rate, is_box, is_card, surcharge_rate, fee_kind=fee_kind
    )
    base = calc_base(snkr_jpy, rate, is_box, is_card, surcharge_rate)
    no_comp = (
        math.ceil(base * (1 + POLICY["no_competition_margin_rate"] / 100) / 1000) * 1000
    )
    is_ov = bool(low_over)
    # [2026-08-02] 시장최저 = 해외/일반/보관 전 판매유형 중 최저. 보관판매(lowest_100/95)를
    # 빼고 계산해 "1등인 줄 알고" 넣은 입찰이 즉시 2등이 되던 것 수정.
    # [2026-08-04] 보관가(lowest_100/95) 를 실제로 포함한다. 주석엔 "호출부가 low_over 에
    # 반영"이라 되어 있었지만 호출부는 lowest_overseas_price 를 그대로 넘길 뿐이라
    # 보관 입찰이 더 싼 옵션에서 '1등인 줄 알고' 등록했다가 다음 사이클에 밀린 걸
    _cands = [x for x in (low_over, low_norm, low_keep) if x and x > 0]
    market_low = min(_cands) if _cands else 0
    # [2026-08-05] 판정 기준은 상황에 따라 **둘로 갈린다**. 하나로 묶어 쓰다가
    # 이미 입찰 중인 건을 '내 가격 vs 내 가격'으로 비교해 스스로 밀린 걸로 오판했다.
    #   ① 신규(cur==0)  — 아직 내 입찰이 없으니 lowest_* 는 순수 경쟁자 값이다.
    #                     통합 최저가보다 싸게 넣으면 1등. market_low 로 판정한다.
    #   ② 기존(cur>0)   — lowest_* 에 내 입찰이 섞인다. 내가 최저면 market_low == 내
    #                     가격이라 비교가 무의미(스스로와 경쟁). 이때는 **내 순위**
    #                     (live_rank)만 본다.
    # live_rank 가 없을 때만 cur <= market_low 로 대신 본다(내가 최저면 1등).
    if cur > 0 and live_rank is not None:
        rank1 = int(live_rank) == 1
    else:
        rank1 = market_low > 0 and 0 < cur <= market_low
    # [2026-08-06] 국내 10% 할인 상한(domestic_cap) 게이트 **폐기**.
    # 종전엔 국내가의 90% 이하로 못 들어가면 지웠다(사이클당 25,021건 제외 — 최대 사유).
    # 최소하한으로 시장 최저를 이길 수 있으면 10% 여유가 없어도 입찰한다.
    # 판정 기준은 '시장 최저(해외/국내/보관 중 최저)를 이기는가' 하나로 통일한다.
    # [2026-08-05] 삭제 게이트는 **1등이 아닐 때만** 본다.
    # 이미 입찰 중이고 내 순위가 1등이면 lowest_* 는 내 입찰 그 자체다. 그걸 상대로
    # "못 이긴다"고 판정하는 건 자기 자신과의 비교라 무의미하고, 그 오판으로 돈 되는
    # 무경쟁 입찰을 계속 지웠다. 1등이면 최저입찰가는 보지 않는다 — 유지·인상만.
    # (실측 147058|235: 나 혼자 567,000, lowest_overseas 도 567,000 = 내 가격)
    if not (cur > 0 and rank1):
        # 최소마진 지키며 시장최저(해외/국내/보관) 못 이기면 1등 확보 불가 → 등록 무의미.
        if market_low > 0 and min_price > market_low:
            return "1등불가삭제", 0, True, False
    # [2026-08-05] 무경쟁 목표가를 국내가(_dcap)로 깎지 않는다.
    # 이 값은 rank1(입찰 중 1등)일 때만 쓰이는데, 1등이면 최저입찰가는 보지 않는 게
    # 규칙이다. 국내 상한으로 눌러 목표가를 낮추면 경쟁자도 없는데 스스로 깎는 꼴.
    no_comp_eff = no_comp
    # 문턱은 정책값(kreamAdjustDeadbandKrw)을 쓴다. 3,000원·3% 는 하드코딩이었다.
    band = int(POLICY.get("adjust_deadband_krw") or 0)
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
        # [2026-08-05] '과가격하향' 폐기 — 경쟁자가 없는데 값을 깎을 이유가 없다.
        # 무경쟁 목표가보다 높게 걸려 있으면 그건 더 버는 것이지 고칠 대상이 아니다.
    else:
        # [2026-08-04] 목표가는 **해외·일반 통합 최저(market_low)** 기준이어야 한다.
        # is_ov(해외 호가 존재)만 보고 해외 최저에서 내리다 보니, 일반이 더 싸면
        # '해외최저-1000' 으로 넣어도 일반 경쟁자에게 그대로 밀렸다. 크림 순위는
        # 일반·해외를 합쳐 매기므로 판매자센터에 '일반 입찰 순번 2~5' 가 쌓였다.
        # rank1 분기는 이미 market_low 기준인데 이 비1등 분기만 빠져 있었다.
        # 틱은 기존과 동일 — 해외 기준 1,000 / 일반 기준 5,000.
        if market_low > 0:
            # [2026-08-13] 틱을 1,000원으로 통일. 종전엔 국내 최저가 기준일 때만 5,000원을
            # 뺐는데, 그러면 1등을 잡는 데 필요한 것보다 4,000원을 더 깎아 마진을 버리고,
            # 5,000원을 뺀 값이 마진 하한 아래로 내려가면 '1등불가삭제'로 지워졌다.
            # 1등은 1,000원만 낮으면 잡힌다(크림 최소 호가 단위 = 1,000원).
            _step = 1000
            market_target = market_low - _step
        else:
            market_target = 0
        if market_target == 0:
            target = max(no_comp, min_price)
        elif market_target == min_price - 1000:
            target = min_price - 1000
        elif market_target < min_price:
            # [2026-08-04] 1등 가격(market_target)이 마진 하한보다 낮으면 1등이 불가능하다.
            # 여기서 min_price 로 올려놓으면 시장최저보다 비싼 값이라 **2등이 확정**되고,
            # 체결도 안 되면서 계속 유지된다(판매자센터 '일반 입찰 순번 2' 다수).
            # 위쪽 `min_price > market_low` 삭제 조건은 min_price <= market_low 인 경계를
            # 못 걸러 이 틈으로 샜다(예: market_low 500,000 / min_price 499,500 /
            # market_target 499,000 → 삭제도 안 되고 1등도 못 감).
            # 2등 입찰은 체결되지 않으므로 유지할 이유가 없다 → 삭제로 보낸다.
            #
            # [2026-08-07] 비교를 `<=` → `<` 로 고친다. **경계 1틱이 통째로 버려지고 있었다.**
            # market_target == min_price 는 "마진 하한을 정확히 지키면서 1등이 되는 가격"이라
            # 삭제가 아니라 등록·유지 대상이다. 그런데 `<=` 라서 이 건들이 전부 지워졌다.
            #   실측(2026-08-07 삭제상세 로그, 표본 20건 중 9건 = 45%):
            #     495687|280 내가격191,000 시장최저190,000 최소가189,000 → market_target 189,000
            #     38207|280  내가격152,000 시장최저151,000 최소가150,000 → market_target 150,000
            #   전부 1등 가능한데 삭제됐다. 사이클당 1등불가 996건 중 약 450건이 이 경우다.
            # 삭제와 등록이 같은 판정기를 쓰므로 리스톡 재등록도 함께 막혀 영구 손실이었다.
            return "1등불가삭제", 0, True, False
        else:
            target = max(market_target, min_price)
        act = "no_rank1추종" if cur != target else "유지"

    if fixed:  # 지정가(사용자 확정가)
        target, act = fixed, ("지정가" if fixed != cur else "유지")
    adjusting = act not in ("유지", "유지(동률)", "무경쟁인상(쿨다운보류)")
    # 하향 20% 캡 — 단, **1순위를 잡는 조정은 면제**한다. [2026-08-13]
    # 판정은 1등 가격(market_low - 틱)을 정확히 내는데 캡이 그걸 도로 끌어올려
    # 2등을 확정시키고 있었다. 예: 내 100,000 / 시장최저 70,000 → target 65,000 인데
    # 캡이 80,000 으로 올려 2등 유지 → 다음 사이클에나 65,000 도달(사이클 74분).
    # 시장가와 25% 이상 벌어지면 한 사이클로는 1등이 구조적으로 불가능했고,
    # 그 사이 시장가가 더 내려가면 영원히 못 따라잡는다(의류/잡화 비1순위 적체).
    # 아래 데드밴드에는 같은 1순위 예외가 이미 있는데(_gains_rank1) 이 층만 빠져 있었다.
    # 헐값 방어는 바로 다음 줄 _ANOMALY_FLOOR(시장최저의 70% 미만 차단)가 그대로 맡고,
    # 마진 하한(min_price) 이상만 면제하므로 손실 위험은 없다.
    _r1_now = market_low > 0 and 0 < target <= market_low and not rank1
    if adjusting and target < cur and not (_r1_now and target >= min_price):
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
        _db = float(POLICY.get("adjust_deadband_krw") or 0)
        if _db > 0 and abs(target - cur) < _db:
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
                    "(resell_matches->'kream'->>'ambiguous')='true' AS ambiguous, "
                    "options::text AS opts, name, "
                    "(resell_matches->'kream'->>'verified')='true' AS verified, "
                    "COALESCE(extra_data->>'currency','JPY') AS currency, "
                    "COALESCE(extra_data->>'snkr_type','') AS snkr_type "
                    "FROM samba_collected_product WHERE source_site='SNKRDUNK' "
                    "AND COALESCE(resell_matches->'kream'->>'product_id','')<>''"
                )
            )
        ).all()
    for snkr_id, kid, ambiguous, opts_txt, name, verified, currency, snkr_type in rows:
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
                "ambiguous": bool(ambiguous),
                "kid": str(kid or ""),
                "name": str(name or ""),
                "verified": bool(verified),  # 검수 확정 — 비카드 리스톡 신규등록 게이트
                # [2026-08-01] 옵션가 통화 — 스니덩크 글로벌은 KRW/USD 로 저장된다.
                # 코드가 전부 JPY 로 가정해 원화값을 엔화로 곱해 9배 부풀린 입찰 사고 발생.
                "currency": str(currency or "JPY").upper(),
                "snkr_type": str(snkr_type or ""),
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
# 카드 브랜드(kid→대문자 브랜드) — 비포켓몬 TCG(원피스/유희왕/MTG 등) 거래게이트 판별용.
# SNKRDUNK 영문 카드명이라 needs_trade 문자열검사가 원피스/유희왕을 못 잡던 사고(2026-07-31)
# 재발 방지: brand 로 확실히 판별. 신발/의류(sneaker/apparel/watch)는 로드서 제외(팬텀PSA 오게이트 방지).
_g_card_brand: dict[str, str] = {}
# [2026-08-06] DB brand 를 크림 브랜드명 표기로 통일했다('포켓몬카드'→'Pokemon TCG',
# 'ONE PIECE'→'One Piece TCG'). 여기 집합은 UPPER(TRIM(brand)) 와 정확일치로 비교하므로
# 통일된 표기를 반드시 포함해야 한다. 종전엔 'POKEMON TCG'·'ONE PIECE TCG' 가 없어
# 원피스 2,080건이 _TCG_BRANDS 에 안 걸려 거래이력 게이트를 통째로 빠져나갔다
# (2026-07-31 사고와 같은 구멍이 표기 차이로 재발). 옛 표기도 남겨 과거 데이터 대비.
_POKEMON_BRANDS = {"POKEMON TCG", "포켓몬카드", "POKÉMON", "POKEMON"}
# 거래이력 게이트 적용 대상 = TCG 브랜드만. 신발/의류 브랜드(NIKE 등)는 제외. [2026-08-02]
_TCG_BRANDS = {
    "POKEMON TCG",
    "포켓몬카드",
    "POKÉMON",
    "POKEMON",
    "ONE PIECE TCG",
    "ONE PIECE",
    "YU-GI-OH OCG",
    "YU-GI-OH!",
    "YU-GI-OH",
    "유희왕",
    "원피스",
    "MAGIC: THE GATHERING",
    "UNION ARENA TCG",
    "UNION ARENA",
    "DUEL MASTERS",
    "DRAGON BALL",
    "MURAKAMI.FLOWERS",
    "TOPPS",
    "WEISS SCHWARZ",
    "VANGUARD",
}


def _is_tcg_brand(brand: str) -> bool:
    """TCG 브랜드인가 — **부분 일치**. [2026-08-06]

    정확 일치로 보면 브랜드 표기가 조금만 달라도 놓친다. 실제로 브랜드를 크림 기준
    ('Pokemon TCG' / 'One Piece TCG')으로 통일한 뒤 검수 화면의 정확일치 판정이
    통째로 깨져 거래이력 게이트가 무력화됐다. 같은 규칙을 쓰는 곳
    (백엔드 / 검수 화면 / samba-tools 의 _verify_rule) 모두 부분 일치로 맞춘다.
    """
    br = str(brand or "").upper()
    return bool(br) and any(t in br for t in _TCG_BRANDS)


def _is_pokemon_brand(brand: str) -> bool:
    br = str(brand or "").upper()
    return bool(br) and any(t in br for t in _POKEMON_BRANDS)


_g_unfulfilled: set[tuple[str, str]] = set()
# 즉시판매 보류 [로컬 이식] — 직전 스냅샷엔 있었는데 지금 사라진 입찰=팔린 것. 주문폴링(랙)
# 을 기다리지 않고 판매 즉시 재입찰 차단. 소싱완료(sourcing_order_number)되면 해제, 6h 만료.
_SET_SNAPSHOT = "kream_ask_snapshot"
_SET_HOLD = "kream_relist_hold"
# [2026-08-03] 우리가 **삭제한** 입찰 기록 — 판매와 구분하기 위해 필요.
# _detect_and_hold_sold 는 "직전 스냅샷에 있었는데 지금 없음"을 전부 판매로 보는데,
# 가격열위 삭제(사이클당 300건대)도 똑같이 사라지므로 팔린 것으로 오인된다.
# 그러면 6시간 재등록 금지가 걸리고, 해제 조건(sourcing_order_number 있는 주문)은
# 삭제분에 존재하지 않아 만료까지 절대 안 풀린다.
# 결과: 삭제할수록 재등록이 막혀 입찰 총량이 계속 줄어든다(21,178 → 20,891, 순감 287).
_SET_DELETED = "kream_deleted_asks"
_DELETED_TTL = 7200  # 2h — 다음 사이클 sold 판정에만 쓰면 되므로 짧게
_g_deleted: dict = {}
_HOLD_TTL = 21600  # 6h


async def _detect_and_hold_sold(asks: list) -> None:
    """직전 스냅샷 대비 사라진 (kid,opt)=판매 → 즉시 보류. 소싱완료·만료분 정리 후
    _g_unfulfilled 에 합쳐 리스톡이 스킵하게 한다. 스냅샷은 현재 라이브로 갱신."""
    import time as _t  # noqa: F811

    now = _t.time()
    try:
        prev = await _load_setting_map(_SET_SNAPSHOT)  # {"kid|opt": ts}
        prev_keys = set(prev.keys())
        cur_keys = {
            f"{a.get('product_id')}|{str(a.get('option') or '').replace(' ', '')}"
            for a in asks
            if a.get("product_id")
        }
        sold = prev_keys - cur_keys
        # 우리가 지운 입찰은 판매가 아니다 — 빼지 않으면 재등록이 6시간 막힌다.
        _g_deleted.update(
            {
                k: float(v)
                for k, v in (await _load_setting_map(_SET_DELETED)).items()
                if now - float(v) < _DELETED_TTL
            }
        )
        _mine = {k for k, v in _g_deleted.items() if now - float(v) < _DELETED_TTL}
        if _mine:
            sold -= _mine
        hold = {
            k: float(v)
            for k, v in (await _load_setting_map(_SET_HOLD)).items()
            if now - float(v) < _HOLD_TTL
        }
        for k in sold:
            hold.setdefault(k, now)  # 최초감지 시각 유지
        # 소싱완료(sourcing_order_number 있음)된 것은 해제
        if hold:
            _kids = list({k.split("|", 1)[0] for k in hold})
            try:
                async with get_read_session() as s:
                    fulfilled = {
                        f"{r[0]}|{str(r[1] or '').replace(' ', '')}"
                        for r in (
                            await s.execute(
                                _text(
                                    "SELECT product_id, product_option FROM samba_order "
                                    "WHERE product_id = ANY(:k) "
                                    "AND COALESCE(sourcing_order_number,'')<>''"
                                ),
                                {"k": _kids},
                            )
                        ).all()
                    }
                hold = {k: v for k, v in hold.items() if k not in fulfilled}
            except Exception:
                pass
        # 리스톡 스킵 대상에 합류
        for k in hold:
            if "|" in k:
                _kid, _opt = k.split("|", 1)
                _g_unfulfilled.add((_kid, _opt))
        await _save_setting_map(_SET_HOLD, hold)
        await _save_setting_map(_SET_SNAPSHOT, {k: now for k in cur_keys})
        await _save_setting_map(
            _SET_DELETED,
            {k: v for k, v in _g_deleted.items() if now - float(v) < _DELETED_TTL},
        )
        if sold:
            _emit_autotune_log(
                "KREAM", "", f"[즉시판매] 사라진 입찰 {len(sold):,}건 → 재입찰 보류"
            )
    except Exception as exc:
        logger.warning("[크림통합] 즉시판매 보류 감지 실패(무시): %s", exc)


_g_recent_posts: dict[str, float] = {}  # "kid|opt" → epoch (2h TTL)
_g_failed_posts: dict[str, float] = {}  # "kid|opt" → epoch (6h TTL)
_g_miss_counts: dict[str, int] = {}  # "kid|opt" → 연속 미검출 횟수
_RECENT_TTL = 7200
_FAILED_TTL = 21600
_SET_RECENT = "kream_recent_posts"
_SET_FAILED = "kream_failed_posts"
_SET_MISS = "kream_miss_counts"
# 리스톡 로테이션 offset 영속화 — 재배포/재시작에도 순회 위치 유지(안 하면 매 재시작 0 리셋 →
# 앞부분만 반복, 뒤쪽 카드 영영 미평가 → 품절 재고갱신·리스톡 누락). [2026-07-25]
_SET_OFFSET = "kream_unified_offset"  # (구) offset 로테이션 — 미사용
_SET_SCANNED = "kream_restock_scanned"  # 이번 바퀴에 본 kid 집합
_SET_LIVE_OFFSET = (
    "kream_live_offset"  # 갱신 로테이션 위치 — 재시작해도 이어가게 영속화
)
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
    # 카드번호/세트명('['·'(' 이후)은 제외하고 판정 — 낱장의 세트명 'Expansion Pack'·
    # '베이스 팩'·'미니멈 팩'의 팩/pack 이 낱장을 밀봉팩으로 오게이트해 거래게이트에
    # 영영 걸리던 버그(포켓몬 낱장 대량 미입찰 원인). 밀봉팩/박스는 카드번호 대괄호가 없다. [2026-07-26]
    head = re.split(r"[\[(]", nm)[0]
    ht = head.lower()
    if _GRADE_RE.search(head):
        return False  # 등급토큰 = 낱장
    if re.search(r"\d{1,3}\s*/\s*\d{1,3}", head):
        return False  # 카드번호(NNN/NNN) = 낱장
    if "박스" in head or "팩" in head or "box" in ht or "pack" in ht:
        return True  # 세트명 제외 후에도 팩/박스 = 진짜 밀봉품
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
    _g_card_brand.clear()
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
            # 카드 브랜드 로드 — 카드만(신발/의류/시계 제외, 팬텀PSA 오게이트 방지).
            # 비포켓몬 TCG 는 영문명이라 needs_trade 가 못 잡음 → brand 로 거래게이트 강제.
            for kid, br in (
                await s.execute(
                    _text(
                        "SELECT resell_matches->'kream'->>'product_id' AS kid, "
                        "UPPER(TRIM(brand)) AS br FROM samba_collected_product "
                        "WHERE source_site='SNKRDUNK' "
                        "AND COALESCE(resell_matches->'kream'->>'product_id','')<>'' "
                        "AND COALESCE(NULLIF(TRIM(brand),''),'')<>'' "
                        "AND COALESCE(extra_data->>'snkr_type','') "
                        "  NOT IN ('sneaker','apparel','watch')"
                    )
                )
            ).all():
                if kid and br:
                    _g_card_brand[str(kid)] = str(br)
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
    """거래이력 게이트 — 거래≥1 필요 상품은 누적거래수≥1 이어야 등록 허용.
    비포켓몬 TCG 카드(원피스/유희왕/MTG/유니온아레나 등)는 SNKRDUNK 영문 카드명이라
    needs_trade 문자열검사가 못 잡음 → brand 로 확실히 판별(2026-07-31 사고 재발방지)."""
    br = _g_card_brand.get(str(kid), "")
    # [2026-08-02] TCG 브랜드 화이트리스트로만 판정 — snkr_type 이 빈 신발/의류가 섞여
    # NIKE 같은 브랜드가 "거래이력없음"으로 잘못 막히던 것 차단. 거래게이트는 TCG 전용.
    if _is_tcg_brand(br) and not _is_pokemon_brand(br):
        # 비포켓몬 TCG = 항상 거래≥1 필수(시세 불안정 → 무리한 입찰 시 소싱불가 손실)
        return _g_trade_counts.get(str(kid), 0) >= 1
    if br and not _is_tcg_brand(br):
        return True  # 신발/의류 등 비TCG — 거래이력 게이트 대상 아님
    # 포켓몬/미상 카드 or 비카드 — 기존 name 기반(팩/박스 + 원피스/유희왕 문자열 폴백)
    if not needs_trade(name):
        return True
    return _g_trade_counts.get(str(kid), 0) >= 1


# 보관 신청 불가 판정된 (kid|opt) — keep 재시도로 불필요한 400 반복 안 하려 캐시.
_keep_impossible: set = set()

# ── 고시정보 자동등록 [2026-08-04 백엔드 이식] ────────────────────────────────
# 크림은 고시정보가 없으면 ask 생성을 거부한다(product_announcement_required).
# 지금까지 백엔드는 그 실패를 잡고 **똑같은 요청을 한 번 더** 보내기만 해서 100% 재실패했다
# (등록 로직은 로컬 봇 _kream_restock_register.register_announcement 에만 있었고 07-22 정지로 끊김).
# 공식 OpenAPI 에는 고시 엔드포인트가 없어 파트너(비공식) API 를 쓴다.
# 토큰: 컨테이너는 웨일 CDP(9223)에 netns 가 달라 못 닿으므로 로컬 _partner_token_sync.py 가
# samba_settings.kream_partner_token 에 넣어둔 값을 읽는다.
_ANN_BASE = "https://partner-api.kream.co.kr/api/v1/products"
_ANN_TOKEN_KEY = "kream_partner_token"
# 사업자 연락처(고시 "A/S 책임자 또는 소비자상담 관련 전화번호", 법정 필수)는
# 설정 > KREAM 의 'A/S 전화번호'(계정 additional_fields.asPhone)에서 읽는다.
# 비어 있으면 등록하지 않는다 — 법정 필수항목이라 지어낼 수 없다.
_ann_tel_cache: list = [0.0, ""]  # [조회시각, 번호]
# 해외 판매자는 원산지·HS코드 필수(누락 시 PUT 400). 원산지=일본(id 4) — 일본 소싱 발송분.
_ANN_COUNTRY_JP = 4
# [2026-08-04] 품목별 HS 정확화 [최우선·관세].
# 종전엔 카드용 9504.40(오락용 카드)을 신발 아닌 전 품목에 박아 **티셔츠를 오락용 카드로
# 신고**하고 있었다(허위신고). 품목별로 반드시 분리한다. id 출처: GET /api/v1/hs-codes 실조회.
_ANN_HS = {
    "shoe": 6,  # 6404.11 스포츠용 신발류
    "top": 11,  # 6109.90 티셔츠·싱글릿(그 밖의 방직용 섬유)
    "knit": 32,  # 6110.30 스웨터·풀오버·후드류(인조섬유)
    "bottom": 18,  # 6203.43 남성용 바지(합성섬유)
    "bag": 87,  # 4202.92 가방(플라스틱 시트·방직용 섬유 외피)
    "headwear": 80,  # 6505.00-9019 모자(그 밖의 섬유)
    "watch": 69,  # 9102.11-9010 손목시계(배터리 구동식)
    "card": 82,  # 9504.40 오락용 카드
}
# 품목 → 고시 카테고리(파트너 마스터 스키마 실제 명칭)
_ANN_CATEGORY = {
    "shoe": "구두/신발",
    "top": "의류",
    "knit": "의류",
    "bottom": "의류",
    "bag": "가방",
    "headwear": "패션잡화(모자/벨트/액세서리)",
    "watch": "시계류",
    "card": "기타 재화",
}
# 마스터 스키마 폴백 [2026-08-04] — 크림 /announcement_info 가 500 을 뱉는 장애가 잦다
# (같은 시각 /hs-codes 는 200 — 고시 엔드포인트만 죽는다). 장애 중에도 등록은 되므로
# 2026-08-04 실조회로 확정한 6개 카테고리 필드키를 폴백으로 둔다.
_ANN_SCHEMA_FALLBACK = {
    "구두/신발": [
        "소재",
        "색상",
        "발길이",
        "굽높이",
        "제조자/수입자",
        "제조국",
        "취급시 주의사항",
        "제조년월",
        "품질보증기준",
        "AS 책임자와 전화번호",
    ],
    "의류": [
        "소재",
        "색상",
        "치수",
        "제조자/수입자",
        "제조국",
        "세탁방법 및 취급시 주의사항",
        "제조년월",
        "품질보증기준",
        "AS 책임자와 전화번호",
    ],
    "가방": [
        "종류",
        "소재",
        "색상",
        "크기",
        "제조자/수입자",
        "제조국",
        "취급시 주의사항",
        "품질보증기준",
        "AS 책임자와 전화번호",
    ],
    "패션잡화(모자/벨트/액세서리)": [
        "종류",
        "소재",
        "치수",
        "제조자/수입자",
        "제조국",
        "취급시 주의사항",
        "품질보증기준",
        "AS 책임자와 전화번호",
    ],
    "시계류": [
        "소재",
        "순도",
        "밴드재질",
        "중량",
        "제조자/수입자",
        "제조국",
        "치수",
        "착용 시 주의사항",
        "주요사양",
        "보증서 제공여부",
        "품질보증기준",
        "AS 책임자와 전화번호",
    ],
    "기타 재화": [
        "품명",
        "모델명",
        "법에 의한 인증·허가 등을 받았음을 확인할 수 있는 경우 그에 대한 사항",
        "제조자/수입자",
        "제조국 또는 원산지",
        "A/S 책임자 또는 소비자상담 관련 전화번호",
    ],
}
_ann_schema_cache: dict = {}
_ann_token_cache: list = [0.0, ""]  # [조회시각, 토큰]
_ann_done: set = set()  # 이 프로세스에서 등록 성공한 kid — 중복 PUT 회피
_ann_stat: dict = {"try": 0, "ok": 0, "no_token": 0, "no_tel": 0, "fail": 0}


async def _partner_token() -> str:
    """파트너 세션 토큰(samba_settings). 5분 캐시 — 수명 8h 라 잦은 조회 불필요."""
    import json as _json  # noqa: F811
    import time as _t  # noqa: F811

    if _ann_token_cache[1] and _t.time() - float(_ann_token_cache[0]) < 300:
        return str(_ann_token_cache[1])
    tok = ""
    try:
        from sqlalchemy import text as _sql_text  # noqa: F811

        async with get_read_session() as s:
            row = (
                await s.execute(
                    _sql_text(
                        "SELECT value, EXTRACT(EPOCH FROM (now() - updated_at))/3600 AS hrs "
                        "FROM samba_settings WHERE key = :k"
                    ),
                    {"k": _ANN_TOKEN_KEY},
                )
            ).first()
        val, _hrs = (row[0], float(row[1] or 0)) if row else (None, 0.0)
        if isinstance(val, str):
            val = _json.loads(val)
        tok = str((val or {}).get("v") or "")
        # [2026-08-13] 토큰이 오래되면 경고. 이 값은 로컬 _partner_token_sync.py 가
        # 20분마다 넣어주는데, 그 루프가 죽으면 조용히 만료된다 — 실측 사고: 8/6 파일정리로
        # 스크립트가 _archive 로 치워져 159시간 정지 → 고시등록 401 → 신규 상품 입찰이
        # 통째로 거부(product_announcement_required)됐고 15시간 동안 아무도 몰랐다.
        # 수명이 8h 라 2h 를 넘기면 루프가 멎었다고 보고 사이클 로그에 남긴다.
        if _hrs > 2:
            logger.warning(
                "[크림통합] 파트너토큰이 %.1f시간째 갱신 안 됨 — "
                "_partner_token_sync.py 루프 확인 필요(고시등록 401 → 신규 입찰 전면 차단)",
                _hrs,
            )
    except Exception as e:
        logger.info("[크림통합] 파트너토큰 조회 실패: %s", str(e)[:80])
    _ann_token_cache[0], _ann_token_cache[1] = _t.time(), tok
    return tok


async def _ann_as_tel() -> str:
    """고시 기재용 사업자 연락처 — 설정 > KREAM 의 A/S 전화번호(asPhone).
    법정 필수 항목이라 지어낼 수 없다. 비어 있으면 호출부가 고시등록을 건너뛴다.
    10분 캐시 — 계정 설정은 자주 안 바뀐다."""
    import time as _t  # noqa: F811

    if _ann_tel_cache[1] and _t.time() - float(_ann_tel_cache[0]) < 600:
        return str(_ann_tel_cache[1])
    tel = ""
    try:
        from sqlalchemy import text as _sql_text

        async with get_read_session() as s:
            r = (
                await s.execute(
                    _sql_text(
                        "SELECT additional_fields->>'asPhone' AS tel "
                        "FROM samba_market_account WHERE market_type='kream' "
                        "AND COALESCE(additional_fields->>'asPhone','')<>'' "
                        "ORDER BY is_default DESC, is_active DESC LIMIT 1"
                    )
                )
            ).first()
        tel = str(r[0]).strip() if r and r[0] else ""
    except Exception as e:
        logger.info("[크림통합] 고시 연락처 조회 실패: %s", str(e)[:80])
    _ann_tel_cache[0], _ann_tel_cache[1] = _t.time(), tel
    return tel


def _ann_kind(snkr_type: str, name: str) -> str:
    """품목 판별 — HS/고시 카테고리의 근거. snkr_type(DB) 우선, 없으면 이름 키워드.
    카드는 마지막 폴백이 아니라 명시 판정으로만 준다(오분류가 곧 관세 허위신고)."""
    t = (snkr_type or "").lower()
    n = (name or "").lower()
    if t == "sneaker":
        return "shoe"
    if t == "watch":
        return "watch"
    if t == "trading-card":
        return "card"
    for kw in ("backpack", "tote", "duffle", "pouch", "waist bag", " bag"):
        if kw in n:
            return "bag"
    for kw in ("cap", "hat", "beanie", "bucket", "belt", "socks", "scarf", "glove"):
        if kw in n:
            return "headwear"
    for kw in ("pants", "shorts", "trouser", "denim", "jeans", "skirt", "slacks"):
        if kw in n:
            return "bottom"
    for kw in (
        "hoodie",
        "sweat",
        "knit",
        "cardigan",
        "jacket",
        "coat",
        "pullover",
        "fleece",
    ):
        if kw in n:
            return "knit"
    if t == "apparel":
        return "top"
    for kw in ("tee", "t-shirt", "shirt", "jersey"):
        if kw in n:
            return "top"
    for kw in ("card", "pack", "box", "booster", "deck", "psa"):
        if kw in n:
            return "card"
    return "card"


def _ann_value(
    key: str, kind: str, name_en: str, style: str, brand: str, tel: str
) -> str:
    """고시 필드 실값 — 지어내지 않는 범위에서 최대한 실제 값.
    [2026-08-04] 종전엔 전 필드를 "제품 내 택 참고"로 채워 품명·모델명·제조자까지
    비워 두고 있었다(허위·부실 기재). 확정 규칙:
      품명=영문명 / 모델명=스타일코드 / 제조자·수입자=브랜드 /
      발길이=150~300mm / 굽높이=1cm / AS 전화=사업자 연락처.
    소재·색상·제조국처럼 우리가 실제로 모르는 값은 지어내지 않고 실물 확인 문구로 둔다."""
    k = key.replace(" ", "")
    if "품명" in k or "품목" in k or k.startswith("도서명"):
        return name_en or style or "제품 내 택 참고"
    if "모델명" in k:
        return style or (name_en or "제품 내 택 참고")
    if "제조자" in k or "수입자" in k or "제조업" in k:
        return brand or "제품 내 택 참고"
    if "전화번호" in k or "연락처" in k:
        return tel
    if "발길이" in k:
        return "150~300mm"
    if "굽높이" in k:
        return "1cm"
    if "종류" in k:
        return {"bag": "가방", "headwear": "패션잡화"}.get(kind, "제품 내 택 참고")
    if "품질보증기준" in k:
        return "관련 법령 및 소비자분쟁해결기준에 따름"
    if "인증" in k or "허가" in k:
        return "해당사항 없음"
    if "보증서" in k:
        return "미제공"
    if "색상" in k:
        return "제품 내 택 참고"
    if "제조국" in k or "원산지" in k or "제조년월" in k or "제조연월" in k:
        return "제품 내 택 참고"
    if "세탁" in k or "취급" in k or "주의" in k or "착용" in k:
        return "제품 내 택 참고"
    return "제품 내 택 참고"


async def _ann_product_row(kid: str) -> dict:
    """고시 기재용 상품정보 — 영문명/스타일코드/브랜드/타입."""
    try:
        from sqlalchemy import text as _sql_text

        async with get_read_session() as s:
            r = (
                (
                    await s.execute(
                        _sql_text(
                            "SELECT name, name_en, style_code, brand, "
                            "extra_data->>'snkr_type' AS t FROM samba_collected_product "
                            "WHERE source_site='SNKRDUNK' "
                            "AND resell_matches->'kream'->>'product_id' = :k LIMIT 1"
                        ),
                        {"k": str(kid)},
                    )
                )
                .mappings()
                .first()
            )
        return dict(r) if r else {}
    except Exception:
        return {}


async def _register_announcement(kid: str) -> bool:
    """고시정보 등록 — 마스터 스키마(/announcement_info)의 카테고리별 필드키에
    품목별 실값을 채워 PUT. 사업자 연락처는 법정 필수항목이라 상수로 고정한다."""
    if str(kid) in _ann_done:
        return True
    _ann_stat["try"] += 1
    tok = await _partner_token()
    if not tok:
        _ann_stat["no_token"] += 1
        return False
    tel = await _ann_as_tel()
    if not tel:
        _ann_stat["no_tel"] += 1
        return False
    hdrs = {
        "Authorization": f"Bearer {tok}",
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://partner.kream.co.kr/",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            if not _ann_schema_cache:
                try:
                    r = await c.get(f"{_ANN_BASE}/announcement_info", headers=hdrs)
                    if r.status_code == 200:
                        for e in r.json() or []:
                            _ann_schema_cache[e["category_name"]] = e["attribute_set"]
                    else:
                        logger.info(
                            "[크림통합] 고시 스키마 %s — 폴백 표 사용", r.status_code
                        )
                except Exception:
                    logger.info("[크림통합] 고시 스키마 조회 실패 — 폴백 표 사용")
                if not _ann_schema_cache:
                    # 폴백은 캐시에 넣지 않는다 — 다음 사이클에 API 가 살아나면
                    # 조회값(41개 전 카테고리)을 다시 쓰게 둔다.
                    schema_now = dict(_ANN_SCHEMA_FALLBACK)
                else:
                    schema_now = _ann_schema_cache
            else:
                schema_now = _ann_schema_cache
            row = await _ann_product_row(kid)
            name_en = str(row.get("name_en") or "").strip()
            style = str(row.get("style_code") or "").strip()
            brand = str(row.get("brand") or "").strip()
            kind = _ann_kind(
                str(row.get("t") or ""), name_en or str(row.get("name") or "")
            )
            # 크림 영문명/스타일코드가 DB 보다 정확 — 있으면 그쪽을 쓴다.
            try:
                g = await c.get(f"{_ANN_BASE}/announcement_infos/{kid}", headers=hdrs)
                rel = ((g.json() or {}).get("product") or {}).get("release") or {}
                name_en = str(rel.get("name") or name_en).strip()
                style = str(rel.get("style_code") or style).strip()
                brand = str(rel.get("brand") or brand).strip()
            except Exception:
                pass
            cat = _ANN_CATEGORY.get(kind, "기타 재화")
            keys = schema_now.get(cat) or schema_now.get("기타 재화")
            if not keys:
                _ann_stat["fail"] += 1
                return False
            body = {
                "category_name": cat,
                "attribute_set": [
                    {
                        "key": k,
                        "value": _ann_value(k, kind, name_en, style, brand, tel),
                    }
                    for k in keys
                ],
                "country_of_origin_id": _ANN_COUNTRY_JP,
                "hs_code_id": _ANN_HS.get(kind, _ANN_HS["card"]),
            }
            # [2026-08-04] 크림 고시 PUT 은 간헐적으로 500 을 뱉는다 — 같은 요청을 바로
            # 다시 보내면 200 이 온다(헤더·본문 문제가 아니라 서버 불안정, 실측 확인).
            # 재시도 없이 한 방에 포기하다 보니 등록 시도 209건 중 168건이 실패했다.
            for _try in range(3):
                p = await c.put(
                    f"{_ANN_BASE}/announcement_infos/{kid}", json=body, headers=hdrs
                )
                if p.status_code in (200, 201):
                    _ann_done.add(str(kid))
                    _ann_stat["ok"] += 1
                    return True
                if p.status_code not in (500, 502, 503, 504):
                    break
                await asyncio.sleep(0.8 * (_try + 1))
            _ann_stat["fail"] += 1
            logger.info(
                "[크림통합] 고시등록 실패 %s %s %s",
                kid,
                p.status_code,
                (p.text or "")[:120],
            )
            return False
    except Exception as e:
        _ann_stat["fail"] += 1
        logger.info("[크림통합] 고시등록 오류 %s: %s", kid, str(e)[:80])
        return False


async def _exec_create_ask(
    cli: httpx.AsyncClient, h: dict, kid: str, price: int, opt: str
) -> tuple[bool, str]:
    """POST /asks 신규 입찰. 보관 전환 신청(is_keep_on_deferred) 명시 — 신규는 미입력 시
    보관 안 됨(2026-07-19). 보관불가 상품(400 '보관 신청이 불가능')은 keep 빼고 재등록.
    반환 (성공, 사유)."""
    _key = f"{kid}|{opt}"
    body = {"product_id": int(kid), "price": int(price), "option": opt}
    if _key not in _keep_impossible:
        body["is_keep_on_deferred"] = True
    try:
        r = await _rq("POST", f"{KREAM_OPENAPI_BASE}/asks", headers=h, json=body)
        if r.status_code in (200, 201):
            return True, "ok"
        detail = str((r.json() or {}).get("detail") or r.text)[:200]
        # 보관 불가 → keep 빼고 재등록(정상 등록 보존)
        if "보관" in detail and "is_keep_on_deferred" in body:
            _keep_impossible.add(_key)
            body.pop("is_keep_on_deferred")
            r = await _rq("POST", f"{KREAM_OPENAPI_BASE}/asks", headers=h, json=body)
            if r.status_code in (200, 201):
                return True, "ok"
            detail = str((r.json() or {}).get("detail") or r.text)[:200]
        return False, detail
    except Exception as exc:
        return False, str(exc)[:120]


async def _exec_delete_ask(
    cli: httpx.AsyncClient, h: dict, ask_id, kid=None, opt=None
) -> bool:
    """삭제 실행. kid/opt 를 주면 '우리가 지운 것'으로 기록해 판매 오인을 막는다."""
    try:
        r = await _rq("DELETE", f"{KREAM_OPENAPI_BASE}/asks/{ask_id}", headers=h)
        ok = r.status_code in (200, 204)
    except Exception:
        return False
    if ok and kid:
        _g_deleted[f"{kid}|{str(opt or '').replace(' ', '')}"] = _now_ts()
    return ok


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


async def _fetch_snkr_apparel_sizes(cli: httpx.AsyncClient, sid: str) -> dict | None:
    """의류·잡화 사이즈별 실시간 최저가 — {옵션명: {price, stock}}. 실패 시 None.

    [2026-08-04] 신발은 mm 옵션(230·275)이라 _SHOE_OPT_RE 로 잡혀 실시간 조회를 받았지만,
    의류는 사이즈가 S/M/L 이라 그 정규식에 안 걸려 _mm_kids 에서 빠졌다. 시세를 못 받으면
    코드가 그 상품을 통째로 스킵해 **의류 비1순위 1,073건이 매 사이클 판단조차 안 됐다**.
    의류는 /v1/apparels/{id}/sizes 가 사이즈별 신품최저가·재고수를 준다(실측).
    """
    try:
        r = await cli.get(
            f"https://snkrdunk.com/v1/apparels/{sid}/sizes",
            headers={
                "User-Agent": _SNKR_HEADERS["User-Agent"],
                "Accept-Language": "ja",
            },
            follow_redirects=True,
        )
        if r.status_code != 200:
            return None
        rows = (r.json() or {}).get("sizePrices") or []
    except Exception:
        return None
    out: dict = {}
    for it in rows:
        nm = str(((it or {}).get("size") or {}).get("localizedName") or "").strip()
        if not nm:
            continue
        price = int(it.get("minNewListingPrice") or 0)
        stock = int(it.get("listingItemCount") or 0)
        out[nm] = {"price": price, "stock": stock}
        # 신발형 표기(26.5cm)도 함께 넣어 크림 mm 옵션과 맞는다
        mm = _cm_to_mm(nm)
        if mm:
            out[mm] = {"price": price, "stock": stock}
    return out or None


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


async def _exec_pending(cli, h, dels: list, upds: list, c: dict) -> None:
    """삭제·갱신 실행 공용기 [2026-08-04].

    카테고리마다 실행 방식이 달랐다 — 신발은 모아서 동시 8, 박스는 판단 루프에서
    건당 즉시 실행(+0.1초 sleep)이라 같은 일에 수십 배 시간이 들었다. 하나로 쓴다.
    dels: [(ask_id, kid, opt)] / upds: [(ask_id, target, cur, is_nc, kid, opt)]
    카운터 키는 호출부와 동일: del / patch / revert / fail
    """
    sem = asyncio.Semaphore(int(os.environ.get("KREAM_EXEC_CONCURRENCY") or 8))

    async def _one_del(_aid, _kid=None, _opt=None):
        async with sem:
            if await _exec_delete_ask(cli, h, _aid, _kid, _opt):
                c["del"] = c.get("del", 0) + 1
            else:
                c["fail"] = c.get("fail", 0) + 1

    async def _one_upd(_aid, _tg, _cur, _nc, _kid, _opt):
        async with sem:
            _res, _r = await _execute_update(cli, h, _aid, _tg, _cur, _nc, _kid, _opt)
            if _res == "ok":
                c["patch"] = c.get("patch", 0) + 1
            elif _res == "reverted":
                c["revert"] = c.get("revert", 0) + 1
            else:
                c["fail"] = c.get("fail", 0) + 1

    if dels:
        await asyncio.gather(*[_one_del(*x) for x in dels])
    if upds:
        await asyncio.gather(*[_one_upd(*x) for x in upds])


def _live_opt(sizes: dict | None, opt: str) -> dict | None:
    """실시간 사이즈맵에서 옵션 하나를 꺼낸다 — 크림 접미('240(US 5.5)'·'230(4Y)') 흡수.

    [2026-08-07] 갱신·삭제와 리스톡이 **같은 매처**를 쓰게 통일한다.
    종전엔 갱신·삭제만 이 규칙을 갖고 리스톡은 DB 옵션을 그대로 읽어,
    같은 옵션을 한쪽은 '있다'(DB 재고1) 다른쪽은 '없다'(실시간 품절)로 봐
    등록↔삭제 왕복이 매 사이클 돌았다(실측 30h: 143건 반복, 최다 11회).
    """
    if not isinstance(sizes, dict):
        return None
    od = sizes.get(opt)
    if od is not None:
        return od
    # [2026-08-07] cm↔mm 양방향. 크림 ask 옵션은 '270'(mm)인데 DB 수집 옵션은
    # '27cm' 이라 접미 폴백만으로는 못 잡는다. 실측 15073: DB '26cm~28.5cm' vs
    # 실시간 '260~285' → 전부 매칭 실패로 재고 0 판정(등록 전멸). 크림 옵션 매칭이
    # 쓰는 _cm_to_mm_variants 를 그대로 써 두 표기를 한쪽으로 모은다.
    _want = {v.replace(" ", "").upper() for v in _cm_to_mm_variants(str(opt))}
    for _k, _v in sizes.items():
        if _want & {x.replace(" ", "").upper() for x in _cm_to_mm_variants(str(_k))}:
            return _v
    _b = re.match(r"^(\d{3}(?:\.\d)?)", str(opt))
    if _b:
        return sizes.get(_b.group(1))
    return None


async def _fetch_snkr_live_sizes(cli: httpx.AsyncClient, snkr_id: str) -> dict | None:
    """비카드 실시간 사이즈별 원가·재고 — 숫자 id는 의류/잡화, 스타일코드는 mm 품목.

    갱신·삭제(_process_shoe_asks._one_style)와 리스톡이 같은 소스를 보게 하는 진입점.
    """
    if str(snkr_id).isdigit():
        return await _fetch_snkr_apparel_sizes(cli, str(snkr_id))
    return await _fetch_snkr_shoe_sizes(cli, str(snkr_id))


def _merge_live_into_db_opts(db_opts: dict | None, sizes: dict | None) -> list:
    """DB 옵션에 실시간 원가·재고를 병합해 write-back 용 options 리스트를 만든다.

    [2026-08-07] 종전 write-back 은 카드(PSA) 전용이라 비카드 DB 옵션이 영영 낡았다.
    입찰 판정은 실시간을 보게 통일했지만, 검수페이지·데일리리포트·즉시수익은 DB 를
    읽으므로 재고/원가가 실제와 어긋난 채 남는다. 실시간 조회에 성공한 상품만 되쓴다.

    - 실시간에 있는 옵션 → 실측 price/stock
    - 실시간에 없는 옵션 → 품절이므로 stock 0, price 는 마지막 값 보존(원가 유실 방지)
    - PSA·밀봉(個/パック/해외배송) 옵션 → 손대지 않음. 카드 write-back·밀봉 전용 경로 소관이라
      여기서 stock 0 을 박으면 남의 데이터를 파괴한다.
    """
    out: list = []
    for _n, _d in (db_opts or {}).items():
        name = str(_n)
        cur_p = int((_d or {}).get("price") or 0)
        cur_s = int((_d or {}).get("stock") or 0)
        if name.upper().startswith("PSA") or _SEALED_OPT_RE.search(name):
            out.append({"name": name, "price": cur_p, "stock": cur_s})
            continue
        lv = _live_opt(sizes, name)
        if lv is None:
            out.append({"name": name, "price": cur_p, "stock": 0})
        else:
            out.append(
                {
                    "name": name,
                    "price": int(lv.get("price") or 0) or cur_p,
                    "stock": int(lv.get("stock") or 0),
                }
            )
    return out


async def _process_shoe_asks(
    asks: list,
    kid_to_opts: dict,
    cooldown,
    rate: float,
    tariff: int,
    h: dict,
    kid_to_snkr: dict | None = None,
    sized_kids: set | None = None,
) -> dict:
    """신발(mm 사이즈)·의류/시계(S/M/L 등) ask 갱신/삭제 — 스니덩크.
    원가·재고는 수집된 DB 옵션(옵션별 price/stock)을 사용 — 신발/의류는 옵션별 실시간
    시세 API가 없어 로컬 봇도 동일하게 DB 옵션을 썼다. 등록(리스톡)은 통합 루프가 담당.
    추가마진은 '나머지(신발·의류)' 정책값 적용, 배송비는 박스(900엔) 기준.
    가격 이상치(상식범위 밖)는 오염 데이터일 수 있어 건드리지 않고 보류 — 오조정 방지.
    _EXEC_SHOE=1 일 때만 실제 PATCH/DELETE.
    sized_kids: 의류/시계(apparel/watch) kid 집합 — 이 kid의 ask는 옵션포맷(S/M/L) 무관하게 관리 대상."""
    _sized = sized_kids or set()
    # 신발(mm) + 의류/시계(kid가 sized_kids) — 옵션포맷 달라도 관리. 카드(PSA)·박스(해외배송) 제외.
    shoe_asks = [
        a
        for a in asks
        if _SHOE_OPT_RE.fullmatch(str(a.get("option") or "").strip())
        or (
            str(a.get("product_id") or "") in _sized
            and not str(a.get("option") or "").upper().startswith("PSA")
            and "해외배송" not in str(a.get("option") or "")
        )
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
    async with httpx.AsyncClient(mounts=_mounts(), timeout=25) as cli:
        # 실행 큐 — 판단 루프는 여기 담기만 하고, 실제 API 호출은 루프 끝나고 병렬 처리
        _pend_del: list = []
        _pend_upd: list = []
        # 상품별 실시간 사이즈시세 1회 조회(입찰이 여러 사이즈여도 페이지는 1번만) — DB 폴백
        live_map: dict = {}
        # [2026-08-02] 신발 입찰이 892건+로 늘며 동시성 6으로는 사이클이 4시간+ 걸려 정지.
        # 스니덩크 동시요청 안전 실증(단일 0.2s) → 동시성 상향. 환경변수로 조절 가능.
        _sem = asyncio.Semaphore(
            int(os.environ.get("KREAM_SHOE_FETCH_CONCURRENCY") or 20)
        )

        async def _one_style(kid: str):
            style = kid_to_snkr.get(kid)
            if not style:
                return
            async with _sem:
                # [2026-08-04] 카테고리 무관 처리 — 스니덩크 id 가 숫자면 의류·잡화라
                # /v1/apparels/{id}/sizes, 스타일코드면 상품 HTML 을 쓴다.
                # [2026-08-07] 분기를 _fetch_snkr_live_sizes 로 빼 리스톡과 공유한다.
                live = await _fetch_snkr_live_sizes(cli, str(style))
            if live is not None:
                live_map[kid] = live

        # [2026-08-04] 브랜드·카테고리 가리지 않고 전량 대상. 종전엔 mm 옵션(230·275)만
        # 뽑아 의류(S/M/L)가 통째로 빠졌고, 시세를 못 받은 상품은 갱신 스킵이라
        # 의류 비1순위 1,073건이 매 사이클 판단조차 안 된 채 남아 있었다.
        _mm_kids = {str(a.get("product_id") or "") for a in shoe_asks}
        # [2026-08-02] 신발 상품 3,000개+ 를 매 사이클 전량 조회하면 사이클이 수시간으로 폭발해
        # 완주(=슬랙)를 못 한다. 카드 리스톡처럼 **로테이션**으로 사이클당 일부만 실시간 조회.
        # 조회 안 된 상품은 이번 사이클 갱신 스킵(다음 회차에 조회) — 가격 방치는 없음.
        # [2026-08-04] 상한·로테이션 제거 — 매 사이클 전량 조회.
        # 나눠 돌면 조회 안 된 상품은 그 사이클 판단 자체를 못 해(갱신·삭제 스킵)
        # 밀린 입찰이 몇 사이클씩 방치됐다.
        _mm_list = sorted(_mm_kids)
        _mm_round = _mm_list
        await asyncio.gather(*[_one_style(k) for k in _mm_round])
        c["live_ok"] = len(live_map)
        c["fetch_round"] = f"{len(_mm_round):,}/{len(_mm_list):,}"
        # [2026-08-07] 갱신·삭제가 본 실시간값을 DB 에도 되쓴다(종전 write-back 은 카드 전용).
        # 입찰 보유 상품은 리스톡 루프를 안 타므로 여기서 챙기지 않으면 계속 낡는다.
        # cost 는 0 = 기존 보존(비카드 DB 원가 원화 오염 이력).
        c["db_updates"] = [
            (
                str(kid_to_snkr[kid]),
                _merge_live_into_db_opts(kid_to_opts.get(kid) or {}, _sz),
                0,
            )
            for kid, _sz in live_map.items()
            if kid_to_snkr.get(kid)
        ]

        for a in shoe_asks:
            kid = str(a.get("product_id") or "")
            opt = str(a.get("option") or "").strip()
            # 실시간 우선: 조회 성공한 상품은 그 값이 진실(매물 없으면 재고0=삭제 후보)
            if kid in live_map:
                # [2026-08-04] 크림 키즈·여성 사이즈는 '240(US 5.5)'·'230(4Y)' 처럼 접미가
                # 붙는다. 스니덩크 시세는 '240' 키라 그대로 조회하면 전부 빗나가
                # 재고·원가를 0 으로 보고 갱신이 통째로 스킵됐다(2,153건 방치).
                # [2026-08-07] 접미 흡수 규칙을 _live_opt 로 빼 리스톡과 공유한다.
                od = _live_opt(live_map[kid], opt) or {"price": 0, "stock": 0}
            else:
                # [2026-08-01 통화사고] DB 폴백 금지 — 신발 DB 원가에 원화(KRW)로 저장된 오염분이
                # 2만개 있어 엔화로 오인하면 9배 부풀린 조정이 나간다. 실시간(JP native, 엔화)
                # 조회 실패 시엔 이번 사이클 건너뛴다(다음 사이클 재시도).
                c["hold"] += 1
                continue
            if od is None:
                c["nocost"] += 1
                continue
            price = int(od.get("price") or 0)
            stock = int(od.get("stock") or 0)
            # 오염 가드 — 신발 원가 상식범위 밖이면 조정/삭제 모두 보류(수집 파싱오류 방어)
            # [2026-08-13] 상한을 300,000 으로 박아둬 정책(kreamMaxCostJpy=350,000)보다
            # 낮았다. 30만~35만엔 원가는 정책상 정상인데 여기서 먼저 hold 로 막혀
            # 갱신도 삭제도 안 됐다. 정책값과 300,000 중 큰 쪽을 쓴다.
            if price and not (5000 <= price <= max(300000, POLICY["max_cost_jpy"])):
                c["hold"] += 1
                continue
            # 입찰 최고 원가 초과 — 신규 등록은 막고, **이미 걸린 입찰은 지운다**.
            # [2026-08-13] 종전엔 continue 로 갱신 대상에서 빼기만 해서, 원가가 오른 뒤
            # 상한을 넘긴 입찰이 영구 방치됐다(실측: 구찌 696883 이 4,152,000원으로 생존).
            # 체결되면 상한 초과 원가로 소싱해야 하므로 방치가 제일 위험한 처리다.
            if price > POLICY["max_cost_jpy"]:
                c["overcost"] = c.get("overcost", 0) + 1
                if _EXEC_SHOE and a.get("id"):
                    _pend_del.append((a.get("id"), kid, opt))
                    c["del_overcost"] = c.get("del_overcost", 0) + 1
                continue
            price = _guard_jpy(kid, opt, price)
            if stock <= 0 or price <= 0:
                c["delete"] += 1
                # [2026-08-04 계측] 삭제 사유 분리 — 신발 삭제가 사이클당 435건이나 되는데
                # c["delete"] 한 곳에 합산돼 재고소진인지 가격열위인지 구분이 안 됐다.
                c["del_nostock"] = c.get("del_nostock", 0) + 1
                if _EXEC_SHOE and a.get("id"):
                    _pend_del.append((a.get("id"), kid, opt))
                continue
            c["stock"] += 1
            cur = int(a.get("price") or 0)
            _min_p = calc_min_price(price, rate, True, False, _sur, fee_kind="item")
            _floor_map[(kid, opt)] = _min_p
            _lo = int(a.get("lowest_overseas_price") or 0)
            _ln = int(a.get("lowest_normal_price") or 0)
            _lk = int(a.get("lowest_100_price") or 0)
            act, target, adjusting, is_nc = _decide_price_action(
                cur,
                opt,
                price,
                _lo,
                _ln,
                (kid, opt) in cooldown,
                0,
                rate,
                tariff,
                is_box=True,
                surcharge_rate=_sur,
                fee_kind="item",  # 신발·의류·시계 = 2,750 + 6.16%
                live_rank=_g_live_rank.get(str(a.get("id"))),
                low_keep=_lk,
            )
            if act in ("국내못이김삭제", "1등불가삭제"):
                if not _price_del_take():
                    c["price_del_skip"] = c.get("price_del_skip", 0) + 1
                else:
                    c["delete"] += 1
                    c["del_price"] = c.get("del_price", 0) + 1
                    if act == "1등불가삭제":
                        c["del_rank1"] = c.get("del_rank1", 0) + 1
                    else:
                        c["del_domestic"] = c.get("del_domestic", 0) + 1
                    # [2026-08-07] 가격열위 삭제 **개별 계측**.
                    # 종전엔 집계(del_rank1=996)만 남아 "무엇을 왜 지웠나"를 사후에 볼 수
                    # 없었다. 삭제된 ask 는 live 목록에서 사라지므로 나중에 재판정해도
                    # 생존분만 보여(생존 편향) 원인 추적이 불가능했다. 값을 그 자리에서 남긴다.
                    _mk = min([x for x in (_lo, _ln, _lk) if x > 0] or [0])
                    _bs = calc_base(price, rate, True, False, _sur)
                    # 마진이 비율이 아니라 최소마진액에 걸린 건 = 마진율을 낮춰도 안 움직인다
                    _by_floor = (_bs * POLICY["competitive_margin_rate"] / 100) < float(
                        POLICY["min_margin_amount"]
                    )
                    if _by_floor:
                        c["del_by_min_margin"] = c.get("del_by_min_margin", 0) + 1
                    if c.get("del_log", 0) < 40:
                        c["del_log"] = c.get("del_log", 0) + 1
                        logger.info(
                            "[크림통합] 삭제상세 %s %s — 내가격%s 시장최저%s(해외%s 국내%s 보관%s) "
                            "최소가%s 원가¥%s %s%s",
                            kid,
                            opt,
                            f"{cur:,}",
                            f"{_mk:,}",
                            f"{_lo:,}",
                            f"{_ln:,}",
                            f"{_lk:,}",
                            f"{_min_p:,}",
                            f"{int(price):,}",
                            act,
                            " [최소마진액지배]" if _by_floor else "",
                        )
                    if _EXEC_SHOE and a.get("id"):
                        _pend_del.append((a.get("id"), kid, opt))
            elif adjusting and target != cur:
                c["renew"] += 1
                if _EXEC_SHOE and a.get("id"):
                    _pend_upd.append((a.get("id"), target, cur, is_nc, kid, opt))

        await _exec_pending(cli, h, _pend_del, _pend_upd, c)
    return c


# 신발 신규 자동등록 사이클당 상한 — 첫등록 폭주 방지(사이즈별 다건). verified 확정 신발만.


def _cm_to_mm_variants(name: str) -> set[str]:
    """옵션명 매칭 후보 — 원본 정규화 + cm→mm(24.5cm→245) + 의류 사이즈 접두 제거.

    [2026-08-05] 의류가 통째로 매칭 실패하고 있었다. 스니덩크는 'JP S'/'US M' 처럼
    지역 접두를 붙여 주는데 크림 옵션은 'S'/'M' 이라 그대로는 못 찾는다.
    실측 177955(adidas Track Jacket): DB 'JP S' vs 크림 'XS/S/M/L/XL/XXL/XXXL' →
    옵션매칭 실패로 등록 시도조차 안 됨. 크림에 호가가 아예 없어(무경쟁) 넣으면
    바로 1등인 건이었다. 신발은 '240(US 5.5)'→'240' 폴백이 있는데 의류만 빠져 있었다.
    """
    raw = str(name or "").strip()
    out = {raw.replace(" ", "").upper()}
    m = re.match(r"^([\d.]+)\s*cm$", raw, re.I)
    if m:
        out.add(str(int(round(float(m.group(1)) * 10))))
    # 지역 접두(JP/US/EU/UK/KR/FR/IT) 제거 — 'JP S' → 'S', 'US M' → 'M'
    m2 = re.match(r"^(?:JP|US|EU|UK|KR|FR|IT)\s+(.+)$", raw, re.I)
    if m2:
        out.add(m2.group(1).replace(" ", "").upper())
    # 반대 방향도 — 크림이 'JP S' 이고 DB 가 'S' 인 경우
    if raw and not re.match(r"^(?:JP|US|EU|UK|KR|FR|IT)\s", raw, re.I):
        out.add(("JP" + raw).replace(" ", "").upper())
    # [2026-08-08] 옵션매칭 실패 전수조사(재고보유 매칭상품 표본 600, 실패율 2.7%) 결과 반영.
    # ① 단일 사이즈 표기 — 스니덩크 'FREE' vs 크림 'ONE SIZE'. 명품 잡화가 대부분 여기 걸려
    #    등록 시도조차 못 했다(실측: 구찌 재고보유 12건 전량 '크림옵션없음' 탈락).
    # ② XL 반복 표기 — 스니덩크 '2XL'/'JP 4XL' vs 크림 'XXL'/'XXXX L'. 숫자형↔반복형 양방향.
    base = {v for v in out}
    for v in base:
        if v in (
            "FREE",
            "F",
            "ONESIZE",
            "ONE SIZE",
            "フリー",
            "프리",
            "원사이즈",
            "JPFREE",
        ):
            out |= {"FREE", "F", "ONESIZE", "프리", "원사이즈"}
        mx = re.fullmatch(r"(\d)XL", v)  # 2XL → XXL
        if mx:
            out.add("X" * int(mx.group(1)) + "L")
        mr = re.fullmatch(r"(X{2,6})L", v)  # XXL → 2XL
        if mr:
            out.add("{}XL".format(len(mr.group(1))))
    return out


# [2026-08-06] 명품 구성 옵션 중 **정품쇼핑백 포함분만** 매칭 금지.
# 크림 명품은 옵션이 사이즈가 아니라 구성인 상품이 있다.
#   실측 61808(구찌 인터로킹 G 펜던트 네클리스, 455535-J8400-0811):
#     본품 750,000 / 본품+박스 / 본품+박스+더스트백 336,000 /
#     본품+박스+더스트백+쇼핑백 390,000
# 소싱처 신품은 박스·더스트백까지는 딸려 오므로 그 구성은 이행할 수 있다.
# 정품쇼핑백은 따로 구하지 못해 그 옵션에 입찰이 붙으면 이행 불가다.
_BUNDLE_OPT_RE = re.compile(r"쇼핑\s*백|shopping\s*bag", re.I)


def is_bundle_option(name: str) -> bool:
    """이행 불가한 구성 옵션인가 — 정품쇼핑백이 들어가면 True."""
    return bool(_BUNDLE_OPT_RE.search(str(name or "")))


def _match_kream_option(nm: str, opts: list) -> dict | None:
    """DB 옵션명 → 크림 옵션 객체. 표기 차이를 흡수한다. [2026-08-05]

    리스톡 매칭이 공백만 지운 **정확 일치**라 표기가 조금만 달라도 등록 시도조차
    못 했다. _cm_to_mm_variants 로 규칙은 이미 만들어 뒀는데 호출부가 0 개였다.
      · 의류 지역 접두 — DB 'JP S' vs 크림 'S'  (실측 177955, 무경쟁인데 미등록)
      · cm 표기      — DB '24.5cm' vs 크림 '245'
      · 크림 접미    — DB '260' vs 크림 '260(US 5.5)'
    """
    if not opts:
        return None
    # 구성(번들) 옵션은 후보에서 제외한다 — 본품만 판매 대상.
    opts = [o for o in opts if not is_bundle_option(o.get("name"))]
    if not opts:
        return None
    want = {v.replace(" ", "").upper() for v in _cm_to_mm_variants(str(nm))}
    norm = [(str(o.get("name") or "").replace(" ", "").upper(), o) for o in opts]
    for n, o in norm:
        if n and n in want:
            return o
    # 크림 접미 표기 — '260(US5.5)' 의 괄호 앞부분으로 한 번 더 본다.
    for n, o in norm:
        base = n.split("(")[0]
        if base and base in want:
            return o
    return None


# [2026-08-05] _process_shoe_restock 제거 — 2026-08-01 에 호출부를 뺀 뒤로 정의만
# 남아 있던 죽은 코드(154줄). 신발/의류 신규등록은 통합 루프의 kind=='restock' 이
# 이미 처리한다(실측: 최근 1시간 등록 1,464건 중 sneaker 757개로 주력).
# 되살리면 같은 일을 두 곳에서 하게 되고, 예전에 그것 때문에 사이클이 느려져 뺐다.

# 박스/카드팩 신규 자동등록 사이클당 상한 — 첫등록 폭주 방지.
# 박스 신규 자동등록 실행 게이트 — 갱신/삭제(_EXEC_BOX)와 별도. 후보 검증 후 1.
_EXEC_BOX_RESTOCK = os.environ.get("KREAM_EXEC_BOX_RESTOCK") == "1"
# 밀봉품(박스/카드팩) 판정 — **옵션명** 기준. [2026-08-03 교체]
# 기존 이름 정규식(박스|카드 ?팩|팩 \()은 '베이스 팩'·'프로모 카드팩' 같은 낱장 카드를
# 386건 오탐하고, 반대로 이름에 팩/박스가 없는 실제 밀봉품은 못 잡았다.
# 스니덩크 밀봉품은 수량옵션(1個 / 10パック)을 갖고 낱장은 PSA 등급옵션만 갖는다 = 확실한 신호.
_SEALED_OPT_RE = re.compile(r"(個|パック)")
# 굿즈 — 스니덩크는 플레이매트·슬리브 같은 주변용품도 수량옵션(1個)을 써서 밀봉품 판정에
# 딸려 들어온다. snkr_type 은 전부 'trading-card' 고 카테고리 필드가 없어 이름이 유일한 단서.
# [2026-08-03] '피규어 컬렉션 미개봉 랜덤박스' 처럼 진짜 밀봉 상품도 있으므로 넓게 잡지 말 것.
# [중요] 크림 상품명은 **영문**(예: 'Pokemon TCG Rubber Playmat …'), 스니덩크 DB name 은 한글.
# 판정 지점마다 언어가 달라 한쪽만 넣으면 조용히 안 걸린다 — 한/영 둘 다 필수.
_GOODS_NAME_RE = re.compile(
    r"플레이\s?매트|러버\s?매트|슬리브|덱\s?케이스|바인더"
    r"|play\s?mat|playmat|rubber\s?mat|sleeve|deck\s?case|binder",
    re.IGNORECASE,
)


def _has_sealed_option(opts_txt: str | None) -> bool:
    """DB options JSON 문자열에 밀봉 수량옵션(1個/10パック)이 있으면 밀봉품(박스·카드팩)."""
    try:
        for o in json.loads(opts_txt or "[]"):
            if isinstance(o, dict) and _SEALED_OPT_RE.search(str(o.get("name") or "")):
                return True
    except Exception:
        return False
    return False


async def _resolve_box_option(cli: httpx.AsyncClient, h: dict, kid: str) -> dict:
    """크림 실제 옵션 확정 — '해외배송' 정확일치 → '해외배송…' 변형 → 옵션 1개뿐이면 그것
    (밀봉품은 단일옵션 'ONE SIZE'로 박힌 상품이 있다). 없으면 빈 dict.

    [2026-08-03] 옵션명만 반환하던 것을 옵션 **dict 전체**로 변경 — 같은 응답에 들어 있는
    lowest_overseas_price/lowest_normal_price 를 버리고 시장가 0(무경쟁)으로 등록하고 있었다.
    신발이 08-02 에 같은 이유로 '등록 즉시 2등' 입찰 7,950건을 쌓은 것과 동일한 구멍."""
    try:
        r = await cli.get(f"{KREAM_OPENAPI_BASE}/products/{kid}", headers=h)
        opts = (r.json() or {}).get("options") or [] if r.status_code == 200 else []
    except Exception:
        return {}
    sel = None
    for o in opts:
        if str(o.get("name") or "") == "해외배송":
            sel = o
            break
    if sel is None:
        for o in opts:
            if str(o.get("name") or "").startswith("해외배송"):
                sel = o
                break
    if sel is None and len(opts) == 1:
        sel = opts[0]
    if sel is None:
        return {}
    # [2026-08-04] 시장최저는 **전 옵션(판매유형) 통합**으로 봐야 한다.
    # 선택 옵션 하나만 보면, 내가 유일한 해외배송 입찰일 때 lowest_overseas_price 가
    # 곧 내 가격이라 "내가 1등"으로 계산된다. 실제 크림 순위는 일반/해외를 합쳐 매기므로
    # 일반배송이 더 싸면 그대로 밀린다(실측: 913591 해외 127,000=내 값 / 일반 102,000
    # → 등록 직후 101등). 카드·신발은 live_rank 로 막았지만 박스 신규등록은 ask 가 없어
    # live_rank 를 못 써서 이 구멍이 남아 있었다.
    _all = [
        v
        for o in opts
        for v in (
            o.get("lowest_overseas_price"),
            o.get("lowest_normal_price"),
            o.get(
                "lowest_100_price"
            ),  # [2026-08-04] 보관 판매도 같은 순위표에 들어간다
        )
        if v and int(v) > 0
    ]
    sel = dict(sel)
    sel["_market_low_all"] = min(int(v) for v in _all) if _all else 0
    return sel


async def _process_box_restock(
    asks: list, cooldown, rate: float, tariff: int, h: dict
) -> dict:
    """박스/카드팩 신규 자동등록 — verified 확정 밀봉품 중 라이브 입찰 없는 것.
    로컬 봇(_kream_restock_register 박스 경로)이 07-22 정지하며 끊긴 경로를 백엔드로 이식.
    카드/신발 리스톡과 동일 가드(2연속miss·재게시·실패쿨·거래이력·이행대기) + 원가상한 +
    정책스킵(1등불가/국내못이김). 원가는 스니덩크 /v1/apparels 1박스 실시세.
    _EXEC_BOX_RESTOCK=1 일 때만 실제 POST. 상한 없이 후보 전량 등록."""
    c = {
        "cand": 0,
        "post": 0,
        "fail": 0,
        "miss": 0,
        "recent": 0,
        "failed": 0,
        "trade": 0,
        "hold": 0,
        "overcost": 0,
        "policy": 0,
        "optmiss": 0,
        "soldout": 0,
        "apifail": 0,
        "capped": 0,
        "goods": 0,
    }
    # 이미 라이브 입찰 있는 kid — 재등록 방지(밀봉품은 상품당 1옵션만 운용)
    live_kids = {
        str(a.get("product_id") or "")
        for a in asks
        if "해외배송" in str(a.get("option") or "")
        or str(a.get("option") or "").strip().upper() == "ONE SIZE"
    }
    _sur = POLICY["box_pack_margin_rate"]
    async with get_read_session() as s:
        rows = (
            await s.execute(
                _text(
                    "SELECT resell_matches->'kream'->>'product_id' AS kid, name, "
                    "split_part(site_product_id, '#', 1) AS sid, options::text AS opts "
                    "FROM samba_collected_product "
                    "WHERE source_site='SNKRDUNK' "
                    "AND COALESCE(resell_matches->'kream'->>'verified','')='true' "
                    "AND COALESCE(resell_matches->'kream'->>'product_id','')<>'' "
                    "AND COALESCE(extra_data->>'snkr_type','') "
                    "  NOT IN ('sneaker','apparel','watch') "
                    # 옵션명 프리필터(정밀 판정은 _has_sealed_option). 이름 LIKE 폐기 이유는
                    # _SEALED_OPT_RE 주석 참조 — 낱장 386건 오탐 + 실밀봉품 누락.
                    "AND options::text ~ '(個|パック)'"
                )
            )
        ).all()
    # 후보 축소 — 라이브 입찰·거래이력 게이트를 API 호출 **전에** 적용해 헛조회를 없앤다.
    cands: list[tuple[str, str, str]] = []
    for kid, name, sid, opts_txt in rows:
        kid, name, sid = str(kid or ""), str(name or ""), str(sid or "")
        if not kid or not sid or kid in live_kids:
            continue
        if not _has_sealed_option(opts_txt):
            continue
        # 굿즈(플레이매트·슬리브)는 밀봉품이 아니다 — 신규등록 대상에서 제외.
        # 이미 등록된 굿즈는 갱신 대상(_load_sealed_kids)에는 남겨 시세 방치를 막는다.
        if _GOODS_NAME_RE.search(name):
            c["goods"] += 1
            continue
        # 밀봉품은 예외 없이 누적거래≥1 필수 — 로컬 봇 박스 경로와 동일.
        # _trade_ok(needs_trade)는 등급토큰(GX 등)을 낱장 신호로 봐서 "프리미엄 트레이너
        # 박스 태그 팀 GX" 같은 박스를 거래0인데 통과시킨다(거래0 박스=체결 후 소싱불가).
        if _g_trade_counts.get(kid, 0) < 1:
            c["trade"] += 1
            continue
        cands.append((kid, name, sid))

    posted = 0
    _now = _now_ts()
    _sem = asyncio.Semaphore(6)
    async with httpx.AsyncClient(mounts=_mounts(), timeout=25) as cli:
        # 스니덩크 박스시세·크림 옵션명 조회는 상품마다 독립 → 동시 6으로 선조회.
        # 순차로 돌리면 후보 수 × API 2회 왕복이 그대로 사이클 시간에 얹힌다.
        # 가드 판정/등록(POST)은 상태 공유(miss·쿨다운·상한)라 아래에서 순차 처리.
        async def _probe(kid: str, name: str, sid: str) -> tuple:
            async with _sem:
                box = await _fetch_snkr_box(cli, sid)
                if box["stock"] <= 0 or box["price"] <= 0:
                    return (kid, name, box, {})
                return (kid, name, box, await _resolve_box_option(cli, h, kid))

        probed = await asyncio.gather(
            *[_probe(k, n, s2) for k, n, s2 in cands], return_exceptions=True
        )
        for _p in probed:
            if isinstance(_p, BaseException):
                c["apifail"] += 1
                continue
            kid, _name, box, _popt = _p
            opt = str(_popt.get("name") or "") if _popt else ""
            if box["stock"] < 0:
                c["apifail"] += 1  # 스니덩크 API 실패 — 다음 사이클 재시도
                continue
            if box["stock"] == 0 or box["price"] <= 0:
                c["soldout"] += 1
                continue
            # [2026-08-03] 급락 가드도 실제 옵션 키로 — 고정 문자열이면 옵션별 직전가가
            # 한 칸에 뒤섞여 가드가 엉뚱한 값을 비교한다.
            jpy = _guard_jpy(kid, opt or "해외배송", int(box["price"]))
            if jpy > POLICY["max_cost_jpy"]:
                c["overcost"] += 1
                continue
            if not opt:
                c["optmiss"] += 1
                continue
            _key = f"{kid}|{opt}"
            # [2026-08-05] 2연속 대기 폐기 — 첫 발견은 무조건 건너뛰던 규칙.
            # 어제까지 탐색이 3,000/사이클·사이클 6시간이라 55,672건 한 바퀴에 4.6일이
            # 걸렸고, 두 번째 만남이 안 와서 하루가 지나도 등록이 안 됐다
            # (실측: 대기 32,257건 적체, 14334 무경쟁 매물도 miss=1 로 묶임).
            # 재고는 스니덩크 실시간 조회로 매 사이클 확인하므로 한 번 더 볼 이유가 없다.
            _g_miss_counts[_key] = int(_g_miss_counts.get(_key, 0)) + 1
            # [2026-08-06] 재게시 쿨다운 폐기 — 위 통합 리스톡과 동일 사유.
            if _key in _g_failed_posts:
                c["failed"] += 1
                continue
            if (kid, opt.replace(" ", "")) in _g_unfulfilled:
                c["hold"] += 1
                continue
            # 시장 최저가 = 크림 상품 옵션 응답(_resolve_box_option 이 이미 받아온 것).
            # 신규등록이라 asks 에는 내 입찰이 없어(항상 빈 dict) 시장가 0=무경쟁으로 계산되던
            # 것을 실시세로 교체 — 1등 불가면 아래 '삭제' 판정으로 등록 자체를 막는다.
            # 전 옵션 통합 최저가를 시장가로 넘긴다(내 값만 되비추는 함정 차단).
            _mlow = int(_popt.get("_market_low_all") or 0)
            act, target, _adj, _nc = _decide_price_action(
                0,
                opt,
                jpy,
                _mlow or int(_popt.get("lowest_overseas_price") or 0),
                _mlow or int(_popt.get("lowest_normal_price") or 0),
                (kid, opt) in cooldown,
                0,
                rate,
                tariff,
                is_box=True,
                surcharge_rate=_sur,
                fee_kind="overseas",  # 박스·카드팩 리스톡 = 1,370 + 3.3%
            )
            if "삭제" in act or target <= 0:
                c["policy"] += 1  # 1등불가/국내못이김 — 등록해도 체결 안 됨
                continue
            c["cand"] += 1
            posted += 1
            if _EXEC_BOX_RESTOCK:
                ok, reason = await _exec_create_ask(cli, h, kid, int(target), opt)
                if (not ok) and ("announcement" in reason or "고시" in reason):
                    # 고시 미등록이면 **먼저 등록**하고 재시도. 등록 없이 같은 요청을
                    # 다시 보내던 종전 코드는 100% 재실패했다.
                    if await _register_announcement(kid):
                        ok, reason = await _exec_create_ask(
                            cli, h, kid, int(target), opt
                        )
                if ok:
                    c["post"] += 1
                    _g_recent_posts[_key] = _now
                    _g_miss_counts.pop(_key, None)
                else:
                    c["fail"] += 1
                    _g_failed_posts[_key] = _now
                    logger.info("[크림통합] 박스등록 실패 %s %s: %s", kid, opt, reason)
                await asyncio.sleep(0.12)
    return c


async def _load_sealed_kids() -> set[str]:
    """밀봉품(박스·카드팩) 크림 상품ID 집합 — 판정은 스니덩크 수량옵션(1個/10パック)."""
    try:
        async with get_read_session() as s:
            rows = (
                await s.execute(
                    _text(
                        "SELECT resell_matches->'kream'->>'product_id' AS kid "
                        "FROM samba_collected_product WHERE source_site='SNKRDUNK' "
                        "AND COALESCE(resell_matches->'kream'->>'product_id','')<>'' "
                        "AND COALESCE(extra_data->>'snkr_type','') "
                        "  NOT IN ('sneaker','apparel','watch') "
                        "AND options::text ~ '(個|パック)'"
                    )
                )
            ).all()
        return {str(r[0]) for r in rows if r[0]}
    except Exception as exc:
        logger.warning("[크림통합] 밀봉품 kid 로드 실패(무시): %s", exc)
        return set()


async def _process_box_asks(
    asks: list,
    kid_to_snkr: dict,
    cooldown,
    rate: float,
    tariff: int,
    h: dict,
    sealed_kids: set[str] | None = None,
) -> dict:
    """박스(해외배송) ask 갱신/삭제 — snkr 박스시세(/v1/apparels) 실시간. 리스톡 미포함.
    _EXEC_BOX=1 일 때만 실제 PATCH/DELETE. API실패(-1)는 삭제금지(보류)."""
    # [2026-08-03] 크림이 단일옵션 'ONE SIZE'로 박아둔 밀봉품이 갱신 사각지대였다
    # (옵션명이 '해외배송'이 아니라 이 필터에 안 걸리고, 카드/신발 pass 대상도 아님).
    # 밀봉 kid 집합으로 한정해 편입 — ONE SIZE 의류/시계를 끌어오지 않는다.
    _sealed = sealed_kids or set()
    box_asks = [
        a
        for a in asks
        if "해외배송" in str(a.get("option") or "")
        or (
            str(a.get("option") or "").strip().upper() == "ONE SIZE"
            and str(a.get("product_id") or "") in _sealed
        )
    ]
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
    async with httpx.AsyncClient(mounts=_mounts(), timeout=20) as scli:

        async def _one(a):
            async with sem:
                kid = str(a.get("product_id") or "")
                opt = str(a.get("option") or "")  # 실제 옵션(해외배송 / 해외배송(N개))
                snkr_id = kid_to_snkr.get(kid)
                if not snkr_id:
                    return ("nocost", a, 0, False)
                # 수량 파싱 — '해외배송(N개)'=N수량 묶음. N수량 실시세를 써야 저평가 안 남.
                _mq = re.search(r"\((\d+)개\)", opt)
                qty = int(_mq.group(1)) if _mq else 1
                if qty > 1:
                    # 다수량 묶음 → /sizes 의 N수량 최저가 사용(낱개×N 금지)
                    sizes = await _fetch_snkr_sizes(scli, snkr_id)
                    if sizes is None:
                        return ("hold", a, 0, False)  # API 실패 — 삭제금지
                    sd = sizes.get(qty)
                    if not sd or sd["stock"] <= 0 or sd["price"] <= 0:
                        return ("delete", a, 0, False)  # 그 수량 매물 없음
                    price = int(sd["price"])
                else:
                    box = await _fetch_snkr_box(scli, snkr_id)
                    if box["stock"] < 0:
                        return ("hold", a, 0, False)
                    if box["stock"] == 0 or box["price"] <= 0:
                        return ("delete", a, 0, False)
                    price = int(box["price"])
                price = _guard_jpy(kid, opt, price)
                # 입찰 최고 원가 초과 — 갱신 대상서 제외(로컬 25만엔 원칙). 삭제는 안 함.
                if price > POLICY["max_cost_jpy"]:
                    return ("overcost", a, 0, False)
                cur = int(a.get("price") or 0)
                _floor_map[(kid, opt)] = calc_min_price(
                    price, rate, True, False, fee_kind="overseas"
                )
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
                    fee_kind="overseas",  # 박스·카드팩 갱신
                    live_rank=_g_live_rank.get(str(a.get("id"))),
                    low_keep=int(a.get("lowest_100_price") or 0),
                )
                if act in ("국내못이김삭제", "1등불가삭제"):
                    return ("pricedel", a, 0, False)  # 가격열위 삭제(상한 적용)
                return (
                    ("renew" if adjusting and target != cur else "keep"),
                    a,
                    target,
                    is_nc,
                    act,
                    price,
                )

        rows = await asyncio.gather(
            *[_one(a) for a in box_asks], return_exceptions=True
        )
        _bsamp: list = []
        # [2026-08-04] 신발과 동일하게 모아서 한 번에 실행(_exec_pending). 종전엔 판단
        # 루프에서 건당 즉시 실행 + 0.1초 sleep 이라 같은 일에 수십 배 시간이 들었다.
        _bx_del: list = []
        _bx_upd: list = []
        for row in rows:
            if isinstance(row, Exception) or not isinstance(row, tuple):
                c["hold"] += 1
                continue
            kind, a, target, is_nc = row[0], row[1], row[2], row[3]
            _bact = row[4] if len(row) > 4 else ""
            _bjpy = row[5] if len(row) > 5 else 0
            if kind == "overcost":
                # [2026-08-13] 상한 초과는 카운트만 하고 방치했다 → 원가가 오른 뒤
                # 상한을 넘긴 입찰이 그대로 살아남는다. 체결되면 상한 초과 원가로
                # 소싱해야 하므로 삭제로 보낸다(신규 등록 차단과 같은 판정).
                c["overcost"] = c.get("overcost", 0) + 1
                if _EXEC_BOX:
                    c["del_overcost"] = c.get("del_overcost", 0) + 1
                    _bx_del.append((a.get("id"), a.get("product_id"), a.get("option")))
            elif kind == "nocost":
                c["nocost"] += 1
            elif kind == "hold":
                c["hold"] += 1
            elif kind == "delete":
                c["delete"] += 1
                if _EXEC_BOX:
                    _bx_del.append((a.get("id"), a.get("product_id"), a.get("option")))
            elif kind == "pricedel":
                if not _price_del_take():
                    c["price_del_skip"] = c.get("price_del_skip", 0) + 1
                else:
                    c["delete"] += 1
                    if _EXEC_BOX:
                        _bx_del.append(
                            (a.get("id"), a.get("product_id"), a.get("option"))
                        )
            elif kind == "renew":
                c["renew"] += 1
                if len(_bsamp) < 8:
                    _bsamp.append(
                        f"{a.get('product_id')} ¥{_bjpy:,} {int(a.get('price') or 0):,}→{target:,}[{_bact}]"
                    )
                if _EXEC_BOX:
                    # [2026-08-03] 실제 옵션을 넘긴다. "해외배송" 고정으로 넘기던 탓에
                    # 쿨다운 기록키(884440|해외배송)와 판정키(884440|ONE SIZE)가 어긋나
                    # 쿨다운이 영원히 안 걸렸고, 마진 하한(_floor_map) 조회도 빗나갔다.
                    _bx_upd.append(
                        (
                            a.get("id"),
                            target,
                            int(a.get("price") or 0),
                            is_nc,
                            str(a.get("product_id")),
                            str(a.get("option") or "해외배송"),
                        )
                    )
        await _exec_pending(scli, h, _bx_del, _bx_upd, c)
    if _bsamp:
        logger.info("[크림통합] 박스 변동샘플: %s", _bsamp)
    return c


_PRICE_DEL_CAP = 10**9  # [2026-08-04] 상한 제거 — 조건이 참이면 전량 즉시 삭제
_price_del_left = 0  # 사이클 시작 시 _PRICE_DEL_CAP 로 리셋


def _price_del_take() -> bool:
    # [2026-08-04] 상한 제거 — 조건이 참이면 전량 즉시 삭제한다.
    # 사이클당 상한(2,000)으로 야금야금 지우면 적체가 언제 끝나는지 알 수 없다.
    return True
    # 이하 미사용(상한 로직 보존 — 되돌릴 때 참고)
    """가격열위 삭제 예산 1건 소진. 남으면 True(삭제 진행), 소진 시 False(이번 사이클 유지)."""
    global _price_del_left
    if _price_del_left <= 0:
        return False
    _price_del_left -= 1
    return True


async def _lookup_snkr_mapping(kid: str) -> tuple[str, str] | None:
    """kid → (snkr_id=site_product_id, source_site). 매핑 없으면 None."""
    async with get_read_session() as s:
        row = (
            await s.execute(
                _text(
                    "SELECT site_product_id, source_site "
                    "FROM samba_collected_product "
                    "WHERE resell_matches->'kream'->>'product_id' = :k "
                    "AND source_site IN ('SNKRDUNK','ONITSUKA') LIMIT 1"
                ),
                {"k": kid},
            )
        ).first()
    if not row:
        return None
    return str(row[0] or ""), str(row[1] or "")


async def _process_expired_asks(
    live_asks: list, h: dict, rate: float, tariff: int
) -> dict:
    """만료(status=expired) 입찰 재입찰 — 신발/박스/카드.

    KREAM ask 수명(~14일)이 다하면 만료탭으로 빠지고 live 목록서 사라져 갱신·리스톡
    어느 pass도 재입찰하지 못한다(로컬 봇이 하던 managed−live 보정을 정지시킨 공백).
    → 매 사이클 만료건을 조회해 '현재 live 없음'인 것만 시세·재고·상한·가드 확인 후 재입찰.
    실행 게이트: 카드=_EXECUTE / 신발=_EXEC_SHOE / 박스=_EXEC_BOX (각 pass와 동일).
    """
    c = {
        "total": 0,
        "cand": 0,
        "post": 0,
        "fail": 0,
        "nomap": 0,
        "onitsuka": 0,
        "nocost": 0,
        "overcost": 0,
        "guard": 0,
        "lines": [],
    }
    try:
        expired = await _fetch_asks_by_status(h, "expired")
    except Exception as exc:
        logger.warning("[크림통합] 만료 입찰 조회 실패(무시): %s", exc)
        return c
    c["total"] = len(expired)
    if not expired:
        return c

    live_keys = {
        (str(a.get("product_id") or ""), str(a.get("option") or "").strip())
        for a in live_asks
    }
    # (kid,opt) 최신 1건만, 현재 live 없는 것만
    seen: dict = {}
    for a in expired:
        kid = str(a.get("product_id") or "")
        opt = str(a.get("option") or "").strip()
        if not kid or not opt or (kid, opt) in live_keys:
            continue
        seen[(kid, opt)] = a  # 페이지 뒤가 최신 → 덮어씀
    cand = list(seen.items())
    c["cand"] = len(cand)
    if not cand:
        return c

    _now = _now_ts()
    _sur_shoe = POLICY["non_card_margin_rate"]
    maxc = POLICY["max_cost_jpy"]
    processed = 0
    async with httpx.AsyncClient(mounts=_mounts(), timeout=25) as cli:
        for (kid, opt), a in cand:
            if False:  # [2026-08-04] 만료회수 상한 제거 — 전량 재등록
                break
            mapping = await _lookup_snkr_mapping(kid)
            if not mapping:
                c["nomap"] += 1
                continue
            snkr_id, site = mapping
            # 오니츠카 재입찰 영구 차단 [2026-07-20 지시] — 되살리면 안 됨.
            if site == "ONITSUKA":
                c["onitsuka"] += 1
                continue
            # 거래게이트(needs_trade)는 한글 팩/박스도 보므로 한글명 우선(영문만 쓰면
            # 'Premium Champion Pack' 이 게이트 통과해 팩/박스 재입찰되던 버그). [2026-07-25]
            pname = str(a.get("product_name_kr") or a.get("product_name") or "")

            # 분류 → 실시간 시세·재고 조회
            is_shoe = bool(_SHOE_OPT_RE.fullmatch(opt))
            is_box = "해외배송" in opt
            is_card = "PSA" in opt.upper()
            price = 0
            stock = 0
            gate = False
            if is_shoe:
                live_sz = await _fetch_snkr_shoe_sizes(cli, snkr_id)
                od = (live_sz or {}).get(opt) or {}
                price = int(od.get("price") or 0)
                stock = int(od.get("stock") or 0)
                target = calc_min_price(
                    price, rate, True, False, _sur_shoe, fee_kind="item"
                )
                gate = _EXEC_SHOE
            elif is_box:
                m = re.search(r"(\d+)개", opt)
                if m:
                    sizes = await _fetch_snkr_sizes(cli, snkr_id) or {}
                    od = sizes.get(int(m.group(1))) or {}
                    price = int(od.get("price") or 0)
                    stock = int(od.get("stock") or 0)
                else:
                    b = await _fetch_snkr_box(cli, snkr_id)
                    price = int(b.get("price") or 0)
                    stock = int(b.get("stock") or 0)
                target = (
                    calc_min_price(price, rate, True, False, fee_kind="overseas")
                    if price > 0
                    else 0
                )
                gate = _EXEC_BOX
            elif is_card:
                used = await _fetch_snkr_used(cli, snkr_id) or {}
                g = "PSA 10" if "10" in opt else ("PSA 9" if "9" in opt else "")
                od = used.get(g) or {}
                price = int(od.get("price") or 0)
                stock = int(od.get("stock") or 0)
                target = calc_min_price(price, rate, False, True)
                gate = _EXECUTE
            else:
                c["nomap"] += 1
                continue

            # 재고·원가 가드
            if price <= 0 or stock <= 0:
                c["nocost"] += 1
                continue
            if price > maxc:
                c["overcost"] += 1
                continue
            # 급락 가드(직전가 대비 폭락 → 저가 재입찰 방지)
            price = _guard_jpy(kid, opt, price)
            # 리스톡 가드 — 재게시/실패 쿨다운 + 거래이력 + 이행대기(판매 후 소싱 전 보류)
            _key = f"{kid}|{opt}"
            # [2026-08-06] 재게시 쿨다운 폐기 — 위 통합 리스톡과 동일 사유.
            if (
                _key in _g_failed_posts
                or not _trade_ok(kid, pname)
                or (kid, opt.replace(" ", "")) in _g_unfulfilled
            ):
                c["guard"] += 1
                continue
            target = _floor_map.get((kid, opt), target)
            if target <= 0:
                c["nocost"] += 1
                continue

            processed += 1
            _emit_autotune_log(
                "KREAM", kid, f"{pname[:40]} ({opt}): 만료 재입찰 {target:,}"
            )
            if not gate:
                continue
            ok, reason = await _exec_create_ask(cli, h, kid, target, opt)
            if (not ok) and ("announcement" in reason or "고시" in reason):
                if await _register_announcement(kid):
                    ok, reason = await _exec_create_ask(cli, h, kid, target, opt)
            if ok:
                c["post"] += 1
                c["lines"].append(f"{pname[:20]} {opt} {target:,}원")
                _g_recent_posts[_key] = _now
                _g_miss_counts.pop(_key, None)
            else:
                c["fail"] += 1
                _g_failed_posts[_key] = _now
            await asyncio.sleep(0.1)
    return c


async def run_kream_unified_once() -> dict:
    """[Step 3 섀도] 스니덩크 전수순회 통합 — 옵션별 갱신/리스톡/삭제 분류. 쓰기 없음(하드오프)."""
    from collections import Counter as _Counter

    import time as _tstart  # noqa: F811

    _cycle_t0 = _tstart.time()  # 사이클 처리속도(avg_sec) 계산용

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
    global _g_price_guard
    _g_price_guard = await _load_setting_map(_SET_GUARD)  # 급락 가드 직전가 로드
    _hb_clamp["used"] = 0  # 입찰제한 보정 상한 리셋
    _rank_fix["used"] = 0  # 순위교정 상한 리셋
    global _price_del_left
    global _noncard_probe_used
    _noncard_probe_used = 0
    _price_del_left = _PRICE_DEL_CAP  # 가격열위 삭제 예산 리셋(사이클당 200)
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
    # [2026-08-03] 조정 전에 실순위부터 확인한다 — 공식 목록은 live_rank 를 안 주고,
    # lowest_* 는 내가 최저일 때 내 가격만 되비춰 '이미 밀린 입찰'을 못 찾았다.
    # 실측: 표본 40건 중 10건이 2등 이하. 로테이션으로 전량을 순차 커버한다.
    try:
        await _load_live_ranks(h, asks)
    except Exception as _e:
        logger.warning("[크림통합] 실순위 조회 실패(기존 로직 진행): %s", str(_e)[:80])
    rate = await _jpy_krw_rate()
    tariff_threshold = int(150 * await _usd_krw_rate())

    # ── 중복입찰 정리 [로컬 이식] — (상품,옵션)당 내 입찰이 2개↑면 최고가 1개만 남기고 삭제.
    # 안 하면 무경쟁 인상 시 안 올린 다른 내 입찰이 rank1 이 돼, 올린 입찰이 rank2 로 밀림 →
    # 재확인 로직이 '경쟁자에 밀림'으로 오인 → 무경쟁 인상↔하향 무한 핑퐁 + 쿨다운 반복.
    # [2026-08-06] **같은 ask id 를 먼저 접는다.** 종전엔 목록에 같은 입찰이 두 번
    # 들어오면 그걸 '중복 입찰'로 보고 하나를 지웠다 — 실재하는 입찰이 사라진다.
    # 라이브 입찰이 25,000건이면 페이지가 511장인데, 넘기는 도중 등록·삭제로 목록이
    # 밀리면 같은 항목이 두 페이지에 걸쳐 들어온다(재시도 수신도 마찬가지).
    # 실측: 총량이 분당 약 23건씩 줄었고, 이 루프의 sleep(0.1)+API 왕복 속도와 일치.
    _seen_ids: set = set()
    _dup: dict = {}
    for a in asks:
        _aid = str(a.get("id") or "")
        if _aid and _aid in _seen_ids:
            continue  # 같은 입찰의 중복 수신 — 중복 '입찰'이 아니다
        if _aid:
            _seen_ids.add(_aid)
        _k = (str(a.get("product_id") or ""), str(a.get("option") or ""))
        _dup.setdefault(_k, []).append(a)
    _dedup_del = 0
    if _EXECUTE:
        async with httpx.AsyncClient(mounts=_mounts(), timeout=25) as _dcli:
            for _k, _grp in _dup.items():
                if len(_grp) < 2:
                    continue
                # [2026-08-05] **최저가를 남긴다.** 종전엔 내림차순 정렬로 최고가를
                # 남기고 더 싼 입찰(=1등)을 지웠다. 크림은 낮은 가격이 1등이므로
                # 남은 최고가는 순위에 밀리고, 다음 갱신에서 "2등 이하"로 또 삭제된다.
                # 이 정리는 대상선정보다 앞에서 돌기 때문에 사이클이 한 바퀴 돌지
                # 않아도 입찰이 사라진다 — 등록이 5,634건 나가도 총량이 안 늘고,
                # 한 사이클 안에 2천건이 빠지던 원인.
                _grp.sort(key=lambda x: int(x.get("price") or 0))  # 최저가(1등) 유지
                for _a in _grp[1:]:
                    if _a.get("id") and await _exec_delete_ask(
                        _dcli, h, _a.get("id"), _a.get("product_id"), _a.get("option")
                    ):
                        _dedup_del += 1
                    await asyncio.sleep(0.1)
    if _dedup_del:
        _emit_autotune_log(
            "KREAM",
            "",
            f"[중복입찰] {_dedup_del:,}건 삭제(최고가 1개만 유지 — 핑퐁 방지)",
        )
        # 삭제분 반영 위해 재조회
        try:
            asks = await _fetch_live_asks(h)
        except Exception:
            pass

    # 검수페이지 '등록여부' 실시간 반영 — 현재 입찰 스냅샷 되쓰기(로컬봇 이식).
    await _write_live_asks_snapshot(asks)

    # live ask 인덱스 (kid, 옵션) → ask (중복 시 최고가 유지)
    ask_index: dict = {}
    for a in asks:
        _ik = (str(a.get("product_id") or ""), str(a.get("option") or ""))
        _prev = ask_index.get(_ik)
        if _prev is None or int(a.get("price") or 0) > int(_prev.get("price") or 0):
            ask_index[_ik] = a
    # [2026-08-06] 크림 옵션명과 DB 옵션명이 달라 '입찰 있음'을 못 알아보던 것 보정.
    # 크림 ask 는 키즈·여성 사이즈에 접미가 붙는다('240(US 5.5)', '235(4.5Y)').
    # DB 는 '240' 이라, 리스톡이 `(kid, DB옵션명) in ask_index` 로 검사하면 이미 걸려
    # 있는 입찰을 못 찾고 '입찰 없음'으로 보고 같은 옵션에 또 등록을 시도한다.
    #   실측(2026-08-06 08:20 KST): 라이브 24,377 중 DB 옵션명과 불일치 3,937건,
    #   그 중 3,807건이 이 '숫자+괄호접미' 형태(82253|240(US 5.5), 407567|235(4.5Y) 등).
    # 괄호 앞부분을 키로 한 보조 인덱스를 만들어 같이 본다.
    ask_base_index: dict = {}
    for (_k, _o), _a in ask_index.items():
        _b = _o.split("(")[0].strip().replace(" ", "")
        if _b and _b != _o:
            ask_base_index.setdefault((_k, _b), _a)

    def _has_live_ask(_kid: str, _opt: str) -> bool:
        """DB 옵션명으로 라이브 입찰 유무 확인 — 크림 접미 표기까지 흡수."""
        if (_kid, _opt) in ask_index:
            return True
        return (_kid, str(_opt).strip().replace(" ", "")) in ask_base_index

    products = await _load_matched_products()
    # 박스 pass용 kid→snkr_id 맵 (배치 슬라이스 전 전체 — 박스 ask는 카탈로그 전역, 로테이션 안 함)
    kid_to_snkr = {
        p["kid"]: p["snkr_id"] for p in products if p["kid"] and p["snkr_id"]
    }
    # 신발 pass용 kid→옵션맵 (사이즈별 price/stock). 배치 슬라이스 전 전체 — 신발 ask도 전역.
    kid_to_opts = {p["kid"]: p["db_opts"] for p in products if p["kid"]}
    # 의류/시계(apparel/watch) kid — 신발 pass 가 옵션포맷(S/M/L) 무관 갱신/삭제하도록 전달.
    async with get_read_session() as _ss:
        _skr = (
            await _ss.execute(
                _text(
                    "SELECT resell_matches->'kream'->>'product_id' "
                    "FROM samba_collected_product WHERE source_site='SNKRDUNK' "
                    "AND extra_data->>'snkr_type' IN ('apparel','watch') "
                    "AND COALESCE(resell_matches->'kream'->>'product_id','')<>''"
                )
            )
        ).all()
    sized_kids = {str(r[0]) for r in _skr if r[0]}
    # ── 처리 대상 선정 [2026-07-22 구조개선] — 갱신과 리스톡의 필요 주기가 다름.
    #  · 갱신(live 입찰 보유): 시세 추종이라 **매 사이클 전량** 처리해야 경쟁에서 안 밀림.
    #    (로컬 봇도 live 입찰은 매 라운드 조정했음. 로테이션에 넣으면 1회전 1.7시간 = 사실상 방치)
    #  · 리스톡 탐색(live 입찰 없음): 신규 재고 발굴이라 급하지 않음 → 나머지만 BATCH 로테이션.
    # 결과: 갱신 5분 주기 + 리스톡 탐색은 계속 순회. 스니덩크 fetch 부담도 상한 유지.
    global _unified_offset, _g_optmiss, _g_skip_samples
    _g_optmiss = {}
    _g_skip_samples = {}
    _g_drop.clear()
    total_products = len(products)
    _live_kids = {k for (k, _o) in ask_index}
    live_products = [p for p in products if p["kid"] in _live_kids]
    # [2026-08-04] 갱신 로테이션 제거 — 라이브 입찰 상품 전량을 매 사이클 갱신한다.
    # 나눠 돌면 순위가 밀린 입찰이 자기 차례(수 사이클)를 기다리는 동안 방치된다.
    rest_products = [p for p in products if p["kid"] not in _live_kids]
    # [2026-08-05 복원] 재고 보유 우선 정렬 — 스캔목록 방식으로 바꾸며 실수로 지웠다.
    # 없으면 DB 순서 그대로 잘려 첫 1만 건의 재고 보유가 3,596건(36%)에 그친다.
    # 스캔목록(_scanned)은 이 정렬 순서를 그대로 따라가므로 재고 보유분이 먼저 소진되고,
    # 그 뒤 재고 0 이 순회된다(재고 복귀 감지 유지).
    rest_products.sort(
        key=lambda p: 0
        if any(
            int((d or {}).get("stock") or 0) > 0
            for d in (p.get("db_opts") or {}).values()
        )
        else 1
    )
    # [2026-08-04] 재고 있는 것 먼저 — 탐색 풀 57,172 중 재고 보유는 20,054(35%)뿐이라
    # 3,000 슬라이스를 뽑아도 등록 가능한 건 ~1,050 밖에 안 됐다(나머지는 재고 0 이라
    # 처리해도 버려진다). 재고 매칭이 1.5만→3만으로 2배가 됐는데 입찰이 안 따라온 원인.
    # 로테이션 자체는 그대로라 재고 0 도 결국 훑는다 — 새로 재고가 생긴 건을 놓치지 않는다.
    # [2026-08-05] offset 로테이션 폐기 → **이번 바퀴에 본 것 배제** 방식.
    #
    # offset 은 정렬과 정면으로 충돌했다. 재고 보유분(약 2만)을 앞에 세워도 슬라이스는
    # 이어받은 위치(34,785)부터 잘라가 재고 없는 뒷구간만 훑었다. 재고 있는 14,785~20,000
    # 구간은 통째로 건너뛰어, 게이트에 하나도 안 걸린 무경쟁 매물(14334 재고1)이 하루
    # 넘게 미등록으로 남았다.
    #
    # 재고 0 을 아예 빼는 것도 답이 아니다 — DB 재고를 갱신하는 건 이 사이클이 실제로
    # 조회한 상품뿐(_write_back_db_options)이라, 빼면 조회도 안 돼 한 번 품절된 상품이
    # 영구 제외된다(재고 복귀를 영영 못 본다).
    #
    # 그래서 "이번 바퀴에 이미 본 kid" 를 기억해 배제한다. 재고 우선 정렬이 그대로
    # 살아나 재고 보유분부터 소진되고, 그 다음 재고 0 이 순회된다. 남은 게 없으면
    # 리셋해 새 바퀴를 시작한다. 건너뛰는 구간이 원천적으로 없다.
    # [2026-08-06] 슬라이스는 **1만 건씩** 끊는다.
    # 전량(0)으로 두니 리셋 직후 56,355 건이 통째로 잡혀 판정 대상이 67,549 가 됐고,
    # 그 한 단계에만 50분 넘게 걸렸다(이전 대상 21,681 일 때 17분).
    # 스캔목록이 '본 것'을 기억하므로 1만씩 끊어도 건너뛰는 구간은 없다.
    # 잔여가 1만 미만이면 아래에서 리셋해 새 바퀴를 시작한다.
    _restock_scan = int(os.environ.get("KREAM_RESTOCK_SCAN") or 10000)
    # [2026-08-06] 리셋 조건을 "하나도 안 남았을 때" → **"1만 건 미만일 때"** 로 바꾼다.
    #
    # 종전 조건(_fresh 가 0)은 사실상 오지 않는다. 매 사이클 신규 매칭이 1~45건씩
    # 들어와 항상 그만큼 남기 때문이다. 그래서 리셋이 영영 안 걸리고, 한 번 스캔된
    # 상품은 다시 보지 않는다 — 코드를 고쳐도 그 상품 차례가 오지 않는다.
    #   실측(2026-08-06 07:55 KST): 리스톡 풀 56,354 / 스캔목록 56,525 / 이번 대상 1건.
    #   177955(adidas Track Jacket, JP S, 재고 1, 크림 무경쟁)는 옵션 매처를 고치기
    #   전에 스캔목록에 올라, 매처 배포 뒤에도 차례가 안 와 계속 미등록이었다.
    # 남은 대상이 한 사이클치(1만)에 못 미치면 새 바퀴를 시작해 전량을 다시 훑는다.
    _reset_below = int(os.environ.get("KREAM_RESTOCK_RESET_BELOW") or 10000)
    _scanned: set = set()
    # [2026-08-06] 프로세스가 새로 뜬 뒤 **첫 사이클은 무조건 리셋**한다.
    # 배포·컨테이너 교체로 사이클이 중간에 죽으면 그때까지 등록하던 슬라이스가
    # 통째로 날아가는데, 스캔목록은 남아 있어 다시 잡히지 않는다
    # (실측 2026-08-06 11:00 KST: 등록 6,604건 중 2,398건만 반영, 4,206건 유실).
    # 새로 떴다 = 직전 사이클이 정상 완주하지 못했을 수 있다 → 처음부터 다시 훑는다.
    global _fresh_boot
    if _fresh_boot:
        _fresh_boot = False
        logger.info("[크림통합] 기동 후 첫 사이클 — 스캔목록 리셋(처음부터 재순회)")
    else:
        try:
            _scanned = set((await _load_setting_map(_SET_SCANNED)).keys())
        except Exception:
            _scanned = set()
    _fresh = [p for p in rest_products if p["kid"] not in _scanned]
    if len(_fresh) < _reset_below:
        logger.info(
            "[크림통합] 리스톡 잔여 %d건 < %d — 스캔목록 리셋(전량 %d건 재순회)",
            len(_fresh),
            _reset_below,
            len(rest_products),
        )
        _scanned = set()
        _fresh = rest_products
    rest_slice = _fresh[:_restock_scan] if _restock_scan > 0 else _fresh
    # [2026-08-05] 스캔목록 저장을 **판정 뒤로** 옮긴다.
    # 종전엔 슬라이스에 뽑자마자 전량 '완료'로 찍고 저장했다. 판정까지 갔는지는
    # 보지 않아서, 조회 상한이나 스니덩크 실패로 한 번도 못 본 상품이 완료로 남고
    # 한 바퀴(5.6만) 내내 다시 안 뽑혔다. 실측 14334: 재고 1·크림 무경쟁인데 하루 넘게
    # 미등록 — 상한이 굶기고 스캔목록이 그걸 처리완료로 덮은 결과.
    _scanned.update(p["kid"] for p in rest_slice)
    _unified_offset = len(_scanned)  # 바퀴 진행률(슬랙·로그 표기용)
    _g_unjudged.clear()
    _instock_n = sum(
        1
        for p in rest_slice
        if any(
            int((d or {}).get("stock") or 0) > 0
            for d in (p.get("db_opts") or {}).values()
        )
    )
    logger.info(
        "[크림통합] 리스톡 풀 %d — 이번 %d건(재고보유 %d) · 바퀴진행 %d/%d",
        len(rest_products),
        len(rest_slice),
        _instock_n,
        len(_scanned),
        len(rest_products),
    )
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
            # [2026-08-03] 밀봉품(박스·카드팩)은 이 통합 루프에서 제외 — 전용 경로
            # (_process_box_asks 갱신 / _process_box_restock 신규등록)가 옵션명 변환
            # (1個·10パック → 크림 '해외배송')과 박스 실시세를 담당한다.
            # 밀봉품 249건에 값 0인 PSA 9/PSA 10 옵션이 박혀 있어(카드 write-back 잔재)
            # has_psa_opt 가 True 로 잡히며 카드 분기로 샜고, 매 사이클 PSA 0/0 을 되써
            # 오염을 재생산하면서 정작 밀봉 옵션은 아무도 등록하지 않았다.
            if any(_SEALED_OPT_RE.search(str(n)) for n in prod["db_opts"]):
                return r
            # [2026-08-04] 옵션이 비면 카드로 인식하지 못해 카드 분기(=PSA 시세 조회 후
            # options write-back)에 못 들어가고, 못 들어가니 옵션이 영영 안 채워진다.
            # 그 상태로 주문이 들어오면 "상품 전체 품절"로 찍혀 재고X 가 붙는다
            # (실측: 옵션 빈 카드 2,521건, snkr_type 도 없어 판정 근거가 아예 없었다).
            # 비카드(신발/의류/시계)로 명시된 것만 제외하고, 나머지 빈 옵션은 카드로 본다.
            # 카드는 옵션이 없어도 /v1/apparels/{id}/used 로 PSA 시세를 받아올 수 있다.
            has_psa_opt = any("PSA" in str(n).upper() for n in prod["db_opts"]) or (
                not prod["db_opts"]
                and prod.get("snkr_type") not in ("sneaker", "apparel", "watch")
            )
            if not has_psa_opt:
                # 비카드(신발/의류/시계/박스) — 같은 사이클·같은 로테이션 안에서 리스톡만 판정.
                # [2026-08-01] 별도 전량조회 경로로 빼면 갱신 사이클이
                # 같이 느려져 20분 주기가 깨진다. 카테고리 구분 없이 이 큐에서 회차마다 이어서.
                r["noncard"] = 1
                if not prod.get("verified"):
                    _drop("검수미확정", kid)  # 검수 확정분만 신규등록 대상
                    return r
                # [2026-08-01 통화가드] 옵션가가 JPY 가 아니면(스니덩크 글로벌 KRW/USD) 등록 금지.
                # 코드 전체가 JPY 가정이라 원화·달러값을 엔으로 곱해 9배~100배 부풀린 입찰 사고 발생
                # (DC7695-003: ¥9,999 상품을 236만원에 입찰). 환산 정합 확인 전까지 차단.
                if str(prod.get("currency") or "JPY").upper() != "JPY":
                    _drop("통화가드(비JPY)", kid, extra=str(prod.get("currency")))
                    return r
                # [2026-08-02] 사이클당 비카드 등록 조회 상한 — 3,500상품 전량 크림조회하면
                # 사이클이 안 끝난다. 상한 넘으면 이번 회차는 판정만 건너뛰고 다음 회차에 처리.
                global _noncard_probe_used
                if _NONCARD_PROBE_MAX and _noncard_probe_used >= _NONCARD_PROBE_MAX:
                    _drop("비카드조회상한", kid)
                    _g_unjudged.add(kid)  # 판정 못 함 — 스캔목록에서 제외
                    return r
                _noncard_probe_used += 1
                # [2026-08-07] 리스톡 원가·재고를 **갱신·삭제와 같은 실시간 소스**로 통일.
                # 종전엔 이 루프만 DB 옵션(db_opts)을 읽었다. DB 는 비카드 실시간 결과를
                # 되쓰지 않아(write-back 은 카드 전용) 낡은 채 남고, 삭제는 실시간을 보니
                # 같은 옵션을 등록쪽 '재고1' / 삭제쪽 '품절' 로 정반대 판정 → 매 사이클 왕복.
                #   실측(2026-08-07, 30h): 반복 등록 143건, 최다 11회.
                #   예) kid 22830 opt 295 — 실시간 255~285(295 없음) 인데 DB 재고1.
                # 조회 실패는 DB 폴백 금지(통화사고 이력) — 이번 회차 건너뛰고 다음에 재시도.
                try:
                    _live_sz = await _fetch_snkr_live_sizes(scli, str(snkr_id))
                except Exception as _e:
                    _live_sz = None
                    _trace(kid, "", f"리스톡 실시간조회 예외: {type(_e).__name__}")
                if _live_sz is None:
                    _drop("실시간조회실패", kid)
                    return r
                # 조회 성공 = 이 상품 재고·원가의 진실을 손에 쥔 시점. DB 에도 되쓴다.
                # cost 는 0 을 넘겨 기존값 보존 — 비카드 DB 원가엔 원화 오염분 이력이 있어
                # 상품 단위 cost 를 덮으면 위험하다. 옵션별 값만 갱신한다.
                r["db_update"] = (
                    snkr_id,
                    _merge_live_into_db_opts(prod.get("db_opts"), _live_sz),
                    0,
                )
                _kream_opts_cache = None  # 상품당 크림 옵션 1회 조회 캐시
                for _nm, _d in (prod.get("db_opts") or {}).items():
                    _lv = _live_opt(_live_sz, _nm) or {}
                    _st, _pr = int(_lv.get("stock") or 0), int(_lv.get("price") or 0)
                    if _st <= 0 or _pr <= 0:
                        _drop("재고0또는원가0", kid, _nm, f"st={_st} pr={_pr}")
                        continue
                    if _has_live_ask(kid, _nm):
                        _trace(kid, _nm, "이미 입찰 있음 — 리스톡 대상 아님")
                        continue
                    # [2026-08-01 오염가드] DB 원가가 상식범위 밖이면 등록 금지.
                    # 실사고: ¥294(실제 ¥40,000)·¥188,000(실제 ¥13,950) 오염값으로 계산해
                    # 56만~262만원 이상입찰 23건(5,595만원) 발생. 신발/의류 하한 5,000엔.
                    if _pr < 5000:
                        _drop("원가하한미달(5000엔)", kid, _nm, f"{_pr}")
                        continue
                    if _pr > POLICY["max_cost_jpy"]:
                        _drop("원가상한초과", kid, _nm, f"{_pr}")
                        continue
                    # [2026-08-06] 비카드 리스톡도 **_decide_price_action 하나로** 판정한다.
                    # 종전엔 이 경로만 _mp/_nc/_tgt 를 직접 계산해, 갱신과 기준이 어긋나면
                    # 등록↔삭제 왕복이 났다(실측: 등록은 해외가만 보고 통과, 갱신은
                    # min(해외,국내,보관)으로 삭제). 판정기를 쓰면 한쪽만 고쳐 어긋날 일이 없다.
                    try:
                        if _kream_opts_cache is None:
                            _pr_resp = await _rq(
                                "GET", f"{KREAM_OPENAPI_BASE}/products/{kid}", headers=h
                            )
                            _kream_opts_cache = (_pr_resp.json() or {}).get(
                                "options"
                            ) or []
                        # 옵션 매칭도 공용 매처로 통일 — 크림 접미('240(US 5.5)')·지역접두
                        # ('JP S')·cm 표기를 한 곳에서 흡수한다.
                        _popt = _match_kream_option(_nm, _kream_opts_cache)
                    except Exception:
                        _popt = None
                    if _popt is None:
                        # 크림에 그 옵션이 없으면 등록 시도 안 함 — POST 해도
                        # "상품 정보가 변경되어..." 로 실패만 소모한다.
                        _drop("크림옵션없음", kid, _nm)
                        continue
                    _nm = str(_popt.get("name") or _nm)  # 크림 실제 옵션명으로 등록
                    _act, _tgt, _adj, _isnc = _decide_price_action(
                        0,
                        _nm,
                        _pr,
                        int(_popt.get("lowest_overseas_price") or 0),
                        int(_popt.get("lowest_normal_price") or 0),
                        (kid, _nm) in cooldown,
                        prod["fixed"].get(_nm, 0),
                        rate,
                        tariff_threshold,
                        is_box=True,
                        surcharge_rate=POLICY["non_card_margin_rate"],
                        fee_kind="item",
                        low_keep=int(_popt.get("lowest_100_price") or 0),
                    )
                    if "삭제" in _act or _tgt <= 0:
                        # [2026-08-07] 등록이 막히는 진짜 이유를 값으로 남긴다.
                        # 마진율을 14%→10% 로 낮춰도 등록이 안 늘던 원인이
                        # min_margin_amount(금액 하한)에 걸린 건인지, 원가 자체가
                        # 시장최저를 못 이기는 건인지 집계로는 구분이 안 됐다.
                        #   margin = max(min_margin_amount, base × competitive_rate/100)
                        # 앞항이 이기면 **마진율을 아무리 낮춰도 최소가가 안 내려간다**.
                        _bs = calc_base(
                            _pr, rate, True, False, POLICY["non_card_margin_rate"]
                        )
                        _by_floor = (
                            _bs * POLICY["competitive_margin_rate"] / 100
                        ) < float(POLICY["min_margin_amount"])
                        _drop(
                            f"리스톡보류({_act})"
                            + ("[최소마진액지배]" if _by_floor else ""),
                            kid,
                            _nm,
                        )
                        continue
                    r["rows"].append(
                        (
                            "restock",
                            "리스톡",
                            kid,
                            _nm,
                            0,
                            _tgt,
                            True,
                            prod["name"],
                            False,
                        )
                    )
                return r
            live = await _fetch_snkr_used(scli, snkr_id) if snkr_id else None
            if live is None:
                r["snkr_fail"] = 1
                _g_unjudged.add(kid)  # 스니덩크 조회 실패 — 판정 못 함
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
            # ── DB write-back [원가/재고 갱신] — 카드는 마켓 미등록이라 메인 오토튠 범위 밖.
            # 로컬 전수스캔이 하던 DB options 갱신이 끊겨 db_opts 가 낡았다(검수/리포트/즉시수익
            # 부정확). kream_shadow 가 매 사이클 실시간 fetch 하므로 그 값을 DB 에 되쓴다.
            # 비PSA(박스/신발) 옵션은 보존, PSA10/9 만 실시간값으로 갱신.
            _base_opts = [
                {
                    "name": _n,
                    "price": int(_d.get("price") or 0),
                    "stock": int(_d.get("stock") or 0),
                }
                for _n, _d in (prod.get("db_opts") or {}).items()
                if not str(_n).upper().startswith("PSA")
            ]
            _new_opts = _base_opts + [
                {
                    "name": "PSA 10",
                    "price": int(_p10.get("price") or 0),
                    "stock": int(_p10.get("stock") or 0),
                },
                {
                    "name": "PSA 9",
                    "price": int(_p9.get("price") or 0),
                    "stock": int(_p9.get("stock") or 0),
                },
            ]
            _new_cost = int(_p10.get("price") or 0) or int(_p9.get("price") or 0)
            # fetch 성공(2311서 None 조기리턴)이므로 소싱품절(cost0)도 실측이다.
            # 재고0·확인시각을 항상 되쓴다(소싱품절 카드 updated_at 이 07-22 동결되던 버그).
            # cost 는 write-back 에서 0 이면 기존값 보존(마지막 원가 유실 방지).
            r["db_update"] = (snkr_id, _new_opts, _new_cost)
            # 크림 옵션(최저가) 조회 캐시 — 상품당 1회. 리스톡 신규등록에서 1등 판정에 쓴다.
            _card_opts_cache: list | None = None
            # PSA10/PSA9만 — 카드는 실시간 snkr(/used) 원가·재고 신뢰
            for nm in ("PSA 10", "PSA 9"):
                d = live.get(nm) or {}
                price = _guard_jpy(kid, nm, int(d.get("price") or 0))
                stock = int(d.get("stock") or 0)
                ask = ask_index.get((kid, nm))
                has_ask = ask is not None
                # 입찰 최고 원가 초과 — 신규 등록은 막고, **이미 걸린 입찰은 지운다**.
                # [2026-08-13] 종전엔 has_ask 여부와 무관하게 overcost 로 빼기만 해서,
                # 원가가 오른 뒤 상한을 넘긴 입찰이 영구 방치됐다. 체결되면 상한 초과
                # 원가로 소싱해야 하므로 등록 차단과 삭제를 한 판정으로 묶는다.
                if price > POLICY["max_cost_jpy"]:
                    r["rows"].append(
                        (
                            "delete" if has_ask else "overcost",
                            "원가상한초과삭제" if has_ask else "원가상한초과",
                            kid,
                            nm,
                            int(ask.get("price") or 0) if has_ask else 0,
                            0,
                            bool(has_ask),
                            prod["name"],
                            False,
                        )
                    )
                    continue
                if has_ask and stock > 0 and price > 0:
                    cur = int(ask.get("price") or 0)
                    low_over = int(ask.get("lowest_overseas_price") or 0)
                    low_norm = int(ask.get("lowest_normal_price") or 0)
                    low_keep = int(ask.get("lowest_100_price") or 0)
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
                        live_rank=_g_live_rank.get(str(ask.get("id"))) if ask else None,
                        low_keep=low_keep,
                    )
                    # 가격열위(국내 못이김/1등불가) 삭제, 아니면 갱신
                    r["rows"].append(
                        (
                            "delete"
                            if act in ("국내못이김삭제", "1등불가삭제")
                            else "renew",
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
                elif has_ask and stock <= 0 and prod.get("ambiguous"):
                    # 중복매핑(ambiguous) 가격불일치 — 어느 snkr 이 진짜 매칭인지 불확실.
                    # 재고0 판단이 무효일 수 있어 삭제 보류(로컬 삭제보류 이식, 오삭제 방지).
                    _cp = int(ask.get("price") or 0)
                    r["rows"].append(
                        (
                            "skip",
                            "삭제보류(중복매핑)",
                            kid,
                            nm,
                            _cp,
                            _cp,
                            False,
                            prod["name"],
                            False,
                        )
                    )
                elif has_ask and stock <= 0:
                    # 재고0 HTML 이중검증 — used API 순간 0 에 정상입찰 오삭제 방지.
                    _hl = await _html_haslisting(scli, snkr_id, nm)
                    if _hl is not False:
                        # True(HTML상 재고있음) 또는 None(확인불가) → 삭제 보류
                        r["rows"].append(
                            (
                                "skip",
                                "삭제보류(HTML재고확인)",
                                kid,
                                nm,
                                int(ask.get("price") or 0),
                                int(ask.get("price") or 0),
                                False,
                                prod["name"],
                                False,
                            )
                        )
                    else:
                        r["rows"].append(
                            (
                                "delete",
                                "삭제(무재고·HTML확인)",
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
                    # [2026-08-05] 리스톡 등록도 **갱신과 같은 _decide_price_action** 을 탄다.
                    # 종전엔 여기서만 자체 계산(calc_base/calc_min_price + 별도 _mkt 판정)을
                    # 해서 등록 기준과 삭제 기준이 어긋났다 — 등록은 일반가만 보고 통과시키고,
                    # 갱신은 일반·해외·보관100 을 다 봐서 1등불가로 지우는 왕복이 났다.
                    # 카드/신발/박스 구분 없이 한 함수, 한 기준으로 판정한다.
                    try:
                        if _card_opts_cache is None:
                            _cr = await _rq(
                                "GET", f"{KREAM_OPENAPI_BASE}/products/{kid}", headers=h
                            )
                            _card_opts_cache = (_cr.json() or {}).get("options") or []
                        _copt = _match_kream_option(nm, _card_opts_cache)
                    except Exception:
                        _copt = None
                    # [2026-08-05] 옵션 매칭 실패 = "시세를 모름"이지 "경쟁자 없음"이 아니다.
                    # 빈 dict 를 넘기면 시세가 전부 0 → market_low=0 → 무경쟁 판정 →
                    # 시세를 무시하고 원가+마진으로 등록해버린다.
                    # 실측 147059|250(7Y): 일반가 119,000 이 있는데 202,000 에 등록 →
                    # 다음 사이클에 1등불가로 삭제되는 왕복. 매칭 실패면 등록을 건너뛴다.
                    if _copt is None:
                        _g_optmiss[f"{kid}|{nm}"] = ",".join(
                            str(_o.get("name") or "") for _o in (_card_opts_cache or [])
                        )[:200]
                        r["rows"].append(
                            (
                                "skip",
                                "리스톡보류(옵션매칭실패)",
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
                    _co = _copt
                    _act, _tgt, _adj, _isnc = _decide_price_action(
                        0,
                        nm,
                        price,
                        int(_co.get("lowest_overseas_price") or 0),
                        int(_co.get("lowest_normal_price") or 0),
                        (kid, nm) in cooldown,
                        prod["fixed"].get(nm, 0),
                        rate,
                        tariff_threshold,
                        low_keep=int(_co.get("lowest_100_price") or 0),
                    )
                    if "삭제" in _act or _tgt <= 0:
                        r["rows"].append(
                            (
                                "skip",
                                f"리스톡보류({_act})",
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
                    r["rows"].append(
                        (
                            "restock",
                            "리스톡",
                            kid,
                            _nm,
                            0,
                            _tgt,
                            True,
                            prod["name"],
                            False,
                        )
                    )
                return r
            live = await _fetch_snkr_used(scli, snkr_id) if snkr_id else None
            if live is None:
                r["snkr_fail"] = 1
                _g_unjudged.add(kid)  # 스니덩크 조회 실패 — 판정 못 함
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
            # ── DB write-back [원가/재고 갱신] — 카드는 마켓 미등록이라 메인 오토튠 범위 밖.
            # 로컬 전수스캔이 하던 DB options 갱신이 끊겨 db_opts 가 낡았다(검수/리포트/즉시수익
            # 부정확). kream_shadow 가 매 사이클 실시간 fetch 하므로 그 값을 DB 에 되쓴다.
            # 비PSA(박스/신발) 옵션은 보존, PSA10/9 만 실시간값으로 갱신.
            _base_opts = [
                {
                    "name": _n,
                    "price": int(_d.get("price") or 0),
                    "stock": int(_d.get("stock") or 0),
                }
                for _n, _d in (prod.get("db_opts") or {}).items()
                if not str(_n).upper().startswith("PSA")
            ]
            _new_opts = _base_opts + [
                {
                    "name": "PSA 10",
                    "price": int(_p10.get("price") or 0),
                    "stock": int(_p10.get("stock") or 0),
                },
                {
                    "name": "PSA 9",
                    "price": int(_p9.get("price") or 0),
                    "stock": int(_p9.get("stock") or 0),
                },
            ]
            _new_cost = int(_p10.get("price") or 0) or int(_p9.get("price") or 0)
            # fetch 성공(2311서 None 조기리턴)이므로 소싱품절(cost0)도 실측이다.
            # 재고0·확인시각을 항상 되쓴다(소싱품절 카드 updated_at 이 07-22 동결되던 버그).
            # cost 는 write-back 에서 0 이면 기존값 보존(마지막 원가 유실 방지).
            r["db_update"] = (snkr_id, _new_opts, _new_cost)
            # 크림 옵션(최저가) 조회 캐시 — 상품당 1회. 리스톡 신규등록에서 1등 판정에 쓴다.
            _card_opts_cache: list | None = None
            # PSA10/PSA9만 — 카드는 실시간 snkr(/used) 원가·재고 신뢰
            for nm in ("PSA 10", "PSA 9"):
                d = live.get(nm) or {}
                price = _guard_jpy(kid, nm, int(d.get("price") or 0))
                stock = int(d.get("stock") or 0)
                ask = ask_index.get((kid, nm))
                has_ask = ask is not None
                # 입찰 최고 원가 초과 — 신규 등록은 막고, **이미 걸린 입찰은 지운다**.
                # [2026-08-13] 종전엔 has_ask 여부와 무관하게 overcost 로 빼기만 해서,
                # 원가가 오른 뒤 상한을 넘긴 입찰이 영구 방치됐다. 체결되면 상한 초과
                # 원가로 소싱해야 하므로 등록 차단과 삭제를 한 판정으로 묶는다.
                if price > POLICY["max_cost_jpy"]:
                    r["rows"].append(
                        (
                            "delete" if has_ask else "overcost",
                            "원가상한초과삭제" if has_ask else "원가상한초과",
                            kid,
                            nm,
                            int(ask.get("price") or 0) if has_ask else 0,
                            0,
                            bool(has_ask),
                            prod["name"],
                            False,
                        )
                    )
                    continue
                if has_ask and stock > 0 and price > 0:
                    cur = int(ask.get("price") or 0)
                    low_over = int(ask.get("lowest_overseas_price") or 0)
                    low_norm = int(ask.get("lowest_normal_price") or 0)
                    low_keep = int(ask.get("lowest_100_price") or 0)
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
                        live_rank=_g_live_rank.get(str(ask.get("id"))) if ask else None,
                        low_keep=low_keep,
                    )
                    # 가격열위(국내 못이김/1등불가) 삭제, 아니면 갱신
                    r["rows"].append(
                        (
                            "delete"
                            if act in ("국내못이김삭제", "1등불가삭제")
                            else "renew",
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
                elif has_ask and stock <= 0 and prod.get("ambiguous"):
                    # 중복매핑(ambiguous) 가격불일치 — 어느 snkr 이 진짜 매칭인지 불확실.
                    # 재고0 판단이 무효일 수 있어 삭제 보류(로컬 삭제보류 이식, 오삭제 방지).
                    _cp = int(ask.get("price") or 0)
                    r["rows"].append(
                        (
                            "skip",
                            "삭제보류(중복매핑)",
                            kid,
                            nm,
                            _cp,
                            _cp,
                            False,
                            prod["name"],
                            False,
                        )
                    )
                elif has_ask and stock <= 0:
                    # 재고0 HTML 이중검증 — used API 순간 0 에 정상입찰 오삭제 방지.
                    _hl = await _html_haslisting(scli, snkr_id, nm)
                    if _hl is not False:
                        # True(HTML상 재고있음) 또는 None(확인불가) → 삭제 보류
                        r["rows"].append(
                            (
                                "skip",
                                "삭제보류(HTML재고확인)",
                                kid,
                                nm,
                                int(ask.get("price") or 0),
                                int(ask.get("price") or 0),
                                False,
                                prod["name"],
                                False,
                            )
                        )
                    else:
                        r["rows"].append(
                            (
                                "delete",
                                "삭제(무재고·HTML확인)",
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
                    # [2026-08-05] 리스톡 등록도 갱신과 같은 _decide_price_action 을 탄다.
                    # 카드/신발/박스 구분 없이 한 함수, 한 기준. 자체 계산은 등록 기준과
                    # 삭제 기준을 어긋나게 해 등록↔삭제 왕복을 만들었다.
                    try:
                        if _card_opts_cache is None:
                            _cr = await _rq(
                                "GET", f"{KREAM_OPENAPI_BASE}/products/{kid}", headers=h
                            )
                            _card_opts_cache = (_cr.json() or {}).get("options") or []
                        _copt = _match_kream_option(nm, _card_opts_cache)
                    except Exception:
                        _copt = None
                    # [2026-08-05] 옵션 매칭 실패 = "시세를 모름"이지 "경쟁자 없음"이 아니다.
                    # 빈 dict 를 넘기면 시세가 전부 0 → market_low=0 → 무경쟁 판정 →
                    # 시세를 무시하고 원가+마진으로 등록해버린다.
                    # 실측 147059|250(7Y): 일반가 119,000 이 있는데 202,000 에 등록 →
                    # 다음 사이클에 1등불가로 삭제되는 왕복. 매칭 실패면 등록을 건너뛴다.
                    if _copt is None:
                        _g_optmiss[f"{kid}|{nm}"] = ",".join(
                            str(_o.get("name") or "") for _o in (_card_opts_cache or [])
                        )[:200]
                        r["rows"].append(
                            (
                                "skip",
                                "리스톡보류(옵션매칭실패)",
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
                    _co = _copt
                    _act, _tgt, _adj, _isnc = _decide_price_action(
                        0,
                        nm,
                        price,
                        int(_co.get("lowest_overseas_price") or 0),
                        int(_co.get("lowest_normal_price") or 0),
                        (kid, nm) in cooldown,
                        prod["fixed"].get(nm, 0),
                        rate,
                        tariff_threshold,
                        low_keep=int(_co.get("lowest_100_price") or 0),
                    )
                    if "삭제" in _act or _tgt <= 0:
                        r["rows"].append(
                            (
                                "skip",
                                f"리스톡보류({_act})",
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
                    r["rows"].append(
                        (
                            "restock",
                            "리스톡",
                            kid,
                            nm,
                            0,
                            _tgt,
                            True,
                            prod["name"],
                            False,
                        )
                    )
                # stock<=0 & no ask → 무동작(카운트 안 함)
            return r

    _emitted = 0
    # [2026-08-02 진단] 사이클이 어느 단계서 멈추는지 로그로 노출 — 4,000건인데도 미완주라
    # 건수 문제가 아님이 확인됨(스니덩크 0.2s). 단계별 소요시간을 찍어 병목을 특정한다.
    import time as _stage_t

    _t_stage = _stage_t.time()
    logger.info(
        "[크림통합] STAGE 조회·판정 시작 (대상 %d — 카드/신발/의류/박스 전량)",
        len(products),
    )
    # [2026-08-06] 판정 진행률 로그. 대상이 6.7만으로 늘면서 이 구간이 50분 넘게
    # 걸리는데 그동안 로그가 한 줄도 없어, 도는 중인지 멈춘 건지 알 수 없었다
    # (실측: 대상 21,681 -> 1,000초 / 67,549 -> 50분+). 2,000건마다 남긴다.
    _done_n = 0
    _prog_every = max(2000, len(products) // 20)

    async def _process_logged(_p, _cli):
        nonlocal _done_n
        try:
            return await _process(_p, _cli)
        finally:
            _done_n += 1
            if _done_n % _prog_every == 0:
                logger.info(
                    "[크림통합] 판정 진행 %d/%d (%.0f%%) %.0f초경과",
                    _done_n,
                    len(products),
                    _done_n * 100.0 / max(1, len(products)),
                    _stage_t.time() - _t_stage,
                )

    async with httpx.AsyncClient(mounts=_mounts(), timeout=20) as scli:
        results = await asyncio.gather(
            *[_process_logged(p, scli) for p in products], return_exceptions=True
        )
    logger.info("[크림통합] STAGE 조회·판정 완료 %.0f초", _stage_t.time() - _t_stage)
    # 판정까지 간 것만 '봤다'로 남긴다 — 못 본 건 다음 사이클에 다시 뽑힌다.
    if _g_unjudged:
        _scanned -= _g_unjudged
        logger.info(
            "[크림통합] 미판정 %d건 — 스캔목록서 제외(다음 사이클 재시도)",
            len(_g_unjudged),
        )
    # [2026-08-06] 스캔목록 저장을 **등록 실행 뒤로** 미룬다(아래 _SET_MISS 저장 옆).
    # 여기서 저장하면 판정만 끝나고 등록 도중 프로세스가 죽었을 때(배포·컨테이너 교체)
    # 그 슬라이스가 '봤음'으로 남아 다음 바퀴까지 통째로 제외된다.
    #   실측(2026-08-06 11:00 KST): 등록 6,604건 실행 중 다른 세션 배포로 컨테이너가
    #   교체돼 2,398건만 반영되고 4,206건이 날아갔다. 그 슬라이스는 이미 '봤음' 이라
    #   재시도도 안 됐다.
    # 등록까지 끝나야 저장하므로, 중간에 죽으면 다음 사이클이 같은 슬라이스를 다시 잡는다.

    # [Step 5] 리스톡 가드 상태 로드 + 실행대기 수집(순차 — 가드상태 race 방지)
    await _load_restock_guards()
    await _detect_and_hold_sold(asks)  # 즉시판매 보류(스냅샷) → _g_unfulfilled 합류
    import time as _t  # noqa: F811

    _now = _t.time()
    pend_renew: list = []  # (kid, nm, target, cur, is_nc)
    pend_restock: list = []  # (kid, nm, target, pname)
    pend_delete: list = []  # (kid, nm)
    rs = {"recent": 0, "failed": 0, "miss": 0, "trade": 0, "hold": 0, "ok": 0}
    psa_snapshot: list = []  # 매수추천/원가오염 감시용 (kid, snkr_id, p10가, p10재고, p9가, p9재고)
    card_instock = 0  # 매물 있는 카드 상품 수 (슬랙 '재고 N건(카드…)')
    db_updates: list = []  # (snkr_id, options, cost) — 실시간값 DB 되쓰기(원가/재고 갱신)

    for res in results:
        if isinstance(res, Exception) or not isinstance(res, dict):
            counts["snkr_fail"] += 1
            continue
        if res.get("db_update"):
            db_updates.append(res["db_update"])
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
                # 거래게이트 위반 기존입찰 등록해제 — needs_trade(팩/박스/유희왕/원피스)인데
                # 거래이력<1 이면 애초에 등록되면 안 됨(체결 시 손해). 갱신 유지 대신 삭제.
                # 이관 전/게이트구멍으로 잘못 입찰된 것 자동 정리 + 재발 방지. [2026-07-25]
                # 안전장치: 거래카운트 로드 실패(빈 맵)면 전 팩/박스 대량삭제 위험 → 스킵.
                if _g_trade_counts and not _trade_ok(kid, pname):
                    counts["delete"] += 1
                    counts["gate_del"] = counts.get("gate_del", 0) + 1
                    pend_delete.append((kid, nm))
                    continue
                if act == "무경쟁인상(쿨다운보류)":
                    counts["cd_blocked"] += 1
                if act == "이상감지차단":
                    counts["anomaly"] += 1
                if adjusting and target != cur:
                    pend_renew.append((kid, nm, target, cur, is_nc))
            elif kind == "delete":
                # 가격열위 삭제(국내못이김/1등불가)는 사이클당 상한(200) 적용 — 점진 삭제.
                # 무재고·HTML확인 삭제는 상한 무관(전량 삭제).
                if act in ("국내못이김삭제", "1등불가삭제"):
                    _skip_note(f"가격열위({act})", kid, nm, f"{cur:,}")
                if act in ("국내못이김삭제", "1등불가삭제") and not _price_del_take():
                    counts["price_del_skip"] = counts.get("price_del_skip", 0) + 1
                    continue
                counts["delete"] += 1
                pend_delete.append((kid, nm))
            elif kind == "restock":
                counts["restock"] += 1
                # 리스톡 가드 (로컬 순서: 2연속miss → 재게시2h → 실패6h → 거래이력 → 이행대기)
                _key = f"{kid}|{nm}"
                # [2026-08-05] 2연속 대기 폐기 — 첫 발견은 무조건 건너뛰던 규칙.
                # 어제까지 탐색이 3,000/사이클·사이클 6시간이라 55,672건 한 바퀴에 4.6일이
                # 걸렸고, 두 번째 만남이 안 와서 하루가 지나도 등록이 안 됐다
                # (실측: 대기 32,257건 적체, 14334 무경쟁 매물도 miss=1 로 묶임).
                # 재고는 스니덩크 실시간 조회로 매 사이클 확인하므로 한 번 더 볼 이유가 없다.
                _g_miss_counts[_key] = int(_g_miss_counts.get(_key, 0)) + 1
                # [2026-08-06] 재게시 쿨다운(2h) **폐기**.
                # 등록에 성공하면 그 입찰은 라이브 목록에 잡히고, 리스톡은 이미
                # _has_live_ask 로 라이브 보유분을 제외한다 — 쿨다운은 중복이다.
                # 반대로 리스톡 후보로 올라왔다는 건 라이브에 없다는 뜻(= 실제로는
                # 등록 안 됨)인데, 이 쿨다운이 그 재시도를 2시간 막았다.
                #   실측(2026-08-06): 리스톡 2,507 중 재게시로 1,920건 차단.
                # 실패 쿨다운(_g_failed_posts, 6h)은 성격이 다르므로 유지한다.
                if _key in _g_failed_posts:
                    rs["failed"] += 1
                    _skip_note("실패쿨다운", kid, nm)
                elif not _trade_ok(kid, pname):
                    rs["trade"] += 1
                    _skip_note("거래게이트", kid, nm, str(pname)[:20])
                elif (str(kid), nm.replace(" ", "")) in _g_unfulfilled:
                    rs["hold"] += 1
                    _skip_note("이행대기", kid, nm)
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
    logger.info(
        "[크림통합] STAGE 실행(삭제/갱신/등록) 시작 %.0f초경과",
        _stage_t.time() - _t_stage,
    )
    if _EXECUTE:
        async with httpx.AsyncClient(mounts=_mounts(), timeout=25) as ecli:
            logger.info("[크림통합] STAGE 실행-삭제 %d건 시작", len(pend_delete))
            # [2026-08-02] 순차+0.1s sleep 이라 건당 ~0.8s → 병렬 8(rate limit 여유).
            # 삭제 65건이 48초 걸리던 것 ~8초로. 사이클 완주 시간의 주 병목이었다.
            _dsem = asyncio.Semaphore(
                int(os.environ.get("KREAM_EXEC_CONCURRENCY") or 8)
            )

            async def _do_del(_kid, _nm):
                nonlocal exec_del, exec_fail
                async with _dsem:
                    _ask = ask_index.get((_kid, _nm))
                    if _ask and await _exec_delete_ask(
                        ecli, h, _ask.get("id"), _kid, _nm
                    ):
                        exec_del += 1
                    else:
                        exec_fail += 1

            await asyncio.gather(*[_do_del(k2, n2) for k2, n2 in pend_delete])
            await _flush_logs_to_db()
            logger.info(
                "[크림통합] STAGE 실행-갱신 %d건 시작 (%.0f초경과)",
                len(pend_renew),
                _stage_t.time() - _t_stage,
            )

            async def _do_renew(_kid, _nm, _tg, _cur, _nc):
                nonlocal exec_patch, exec_revert, exec_fail
                async with _dsem:
                    _ask = ask_index.get((_kid, _nm))
                    if not _ask:
                        return
                    _res, _r2 = await _execute_update(
                        ecli, h, _ask.get("id"), _tg, _cur, _nc, _kid, _nm
                    )
                    if _res == "ok":
                        exec_patch += 1
                    elif _res == "reverted":
                        exec_revert += 1
                    else:
                        exec_fail += 1

            await asyncio.gather(
                *[_do_renew(a1, a2, a3, a4, a5) for a1, a2, a3, a4, a5 in pend_renew]
            )
            await _flush_logs_to_db()
            logger.info(
                "[크림통합] STAGE 실행-등록 %d건 시작 (%.0f초경과)",
                len(pend_restock),
                _stage_t.time() - _t_stage,
            )
            # 등록도 병렬(동시 4) — 순차일 때 150건 170초. 고시등록이 CDP 토큰을 쓰므로
            # 삭제/갱신(8)보다 낮게 잡아 파트너 세션 부담을 줄인다.
            _psem = asyncio.Semaphore(
                int(os.environ.get("KREAM_POST_CONCURRENCY") or 4)
            )

            async def _do_post(_kid, _nm, _tg, _pn):
                nonlocal exec_post, exec_fail
                async with _psem:
                    _ok, _rs = await _exec_create_ask(ecli, h, _kid, _tg, _nm)
                    if (not _ok) and ("announcement" in _rs or "고시" in _rs):
                        if await _register_announcement(_kid):
                            _ok, _rs = await _exec_create_ask(ecli, h, _kid, _tg, _nm)
                    if _ok:
                        exec_post += 1
                        # 슬랙 리스톡 섹션 등록줄 (로컬 포맷: "{상품명20} {옵션} {가격}원")
                        registered_lines.append(f"{str(_pn)[:20]} {_nm} {_tg:,}원")
                        _g_recent_posts[f"{_kid}|{_nm}"] = _now
                        _g_miss_counts.pop(f"{_kid}|{_nm}", None)
                    else:
                        exec_fail += 1
                        # [2026-08-06] 등록 실패 **사유를 남긴다.** 종전엔 건수만 세고
                        # 사유는 버렸다. 특히 고시·500 실패는 쿨다운에도 안 들어가
                        # 어느 저장소에도 흔적이 없었다 — '이유 없이 등록 안 되는 건'의
                        # 정체가 이것이다(실측: 등록가능 판정 27건 중 23건이 miss_counts
                        # 에만 남고 failed_posts 엔 없음).
                        _drop(f"등록실패({_fail_kind(_rs)})", _kid, _nm, _rs[:60])
                        # [2026-08-04] 고시 API 500 같은 **일시 서버 장애**로 실패한 건은
                        # 6h 쿨다운에 넣지 않는다. 상품 문제가 아니라 크림 쪽 불안정이라
                        # 다음 사이클에 그냥 되는데, 쿨다운에 갇혀 6시간을 버렸다
                        # (한 사이클에 168건이 이 경로로 묶였다).
                        if not ("announcement" in _rs or "고시" in _rs or "500" in _rs):
                            _g_failed_posts[f"{_kid}|{_nm}"] = _now

            await asyncio.gather(
                *[_do_post(b1, b2, b3, b4) for b1, b2, b3, b4 in pend_restock]
            )
            await _flush_logs_to_db()
        await _save_setting_map(_SET_RECENT, _g_recent_posts)
        await _save_setting_map(_SET_FAILED, _g_failed_posts)
    # 등록 실행까지 마쳤으므로 이제 '봤음'으로 확정한다(위 [2026-08-06] 주석 참조).
    await _save_setting_map(_SET_SCANNED, {k: 1 for k in _scanned})
    await _save_setting_map(
        _SET_MISS, _g_miss_counts
    )  # 2연속 대기 상태는 섀도서도 유지
    await _save_setting_map(_SET_LIMIT, _g_limit_cd)  # 입찰제한 쿨다운 유지
    await _save_setting_map(_SET_GUARD, _g_price_guard)  # 급락 가드 직전가 유지

    # ── [B] 신발(mm) 갱신/삭제 — 전역 ask 대상. DB 옵션(사이즈별) 원가. _EXEC_SHOE 게이트.
    logger.info("[크림통합] STAGE 신발갱신 시작 %.0f초경과", _stage_t.time() - _t_stage)
    shoe = await _process_shoe_asks(
        asks, kid_to_opts, cooldown, rate, tariff_threshold, h, kid_to_snkr, sized_kids
    )
    # 갱신·삭제가 조회한 실시간값도 되쓰기 대상에 합친다(5126 _write_back_db_options).
    db_updates.extend(shoe.get("db_updates") or [])
    logger.info(
        "[크림통합] 신발(mm) %d — 실시간%d 재고%d 갱신%d 삭제%d[재고0:%d 1등불가:%d 국내못이김:%d 가격열위보류:%d "
        "최소마진액지배:%d] 보류%d 원가없음%d / 실행[갱신%d 삭제%d 복귀%d 실패%d] (%s)",
        shoe["total"],
        shoe.get("live_ok", 0),
        shoe["stock"],
        shoe["renew"],
        shoe["delete"],
        shoe.get("del_nostock", 0),
        shoe.get("del_rank1", 0),
        shoe.get("del_domestic", 0),
        shoe.get("price_del_skip", 0),
        # 마진율이 아니라 금액 하한(min_margin_amount)에 걸려 지워진 건.
        # 이 수가 크면 마진율을 낮춰도 등록·유지가 안 늘어난다.
        shoe.get("del_by_min_margin", 0),
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
            f"복귀{shoe['revert']:,}{_fail_tag(shoe['fail'])} "
            f"({'실행ON' if _EXEC_SHOE else '섀도'})",
        )

    # ── [A] 박스(해외배송) 갱신/삭제 — 전역 ask 대상(배치 무관). _EXEC_BOX 게이트.
    logger.info("[크림통합] STAGE 박스갱신 시작 %.0f초경과", _stage_t.time() - _t_stage)
    _sealed_kids = await _load_sealed_kids()
    box = await _process_box_asks(
        asks, kid_to_snkr, cooldown, rate, tariff_threshold, h, _sealed_kids
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
            f"보류{box['hold']:,} / 실행 갱신{box['patch']:,} 삭제{box['del']:,} 복귀{box['revert']:,}"
            f"{_fail_tag(box['fail'])} ({'실행ON' if _EXEC_BOX else '섀도'})",
        )

    # ── [B-2/B-3 제거·2026-08-01] 신발/의류/박스 신규등록은 별도 전량조회 경로였다 →
    # 갱신 사이클이 같이 느려져 20분 주기가 깨졌다. 이제 _process(리스톡 로테이션) 안에서
    # 카테고리 구분 없이 회차마다 이어서 처리한다.
    shoe_rs = {"cand": 0, "post": 0, "fail": 0}
    # [B-3 복구·2026-08-03] 박스/카드팩 신규등록 — 2026-08-01 에 "통합 리스톡이 대신 처리한다"며
    # 호출을 지웠으나, 통합 루프는 밀봉 옵션(1個/10パック)을 크림 옵션(해외배송)으로 변환하지
    # 못해 실제로는 아무도 등록하지 않았다(입찰 박스 4건·카드팩 0건에서 정체).
    # 옵션명 변환·박스 실시세·거래이력 게이트를 갖춘 전용 경로를 다시 호출한다.
    # 신발/의류 신규등록은 통합 루프가 옵션포맷 그대로 처리하므로 그대로 둔다.
    box_rs = await _process_box_restock(asks, cooldown, rate, tariff_threshold, h)
    # 박스 경로가 올린 2연속 대기(miss)·재게시/실패 쿨다운은 위 저장 시점(카드 리스톡 직후)
    # **뒤에** 생긴다. 여기서 다시 저장하지 않으면 다음 사이클 _load_restock_guards 가
    # 옛 값을 되살려 miss 가 영원히 1 에 머물고 등록이 한 건도 안 나간다.
    # (2026-08-03 실측: 미검출 161 → 163 반복, 등록 0)
    await _save_setting_map(_SET_MISS, _g_miss_counts)
    if box_rs.get("post") or box_rs.get("fail"):
        await _save_setting_map(_SET_RECENT, _g_recent_posts)
        await _save_setting_map(_SET_FAILED, _g_failed_posts)
    if box_rs.get("cand") or box_rs.get("trade") or box_rs.get("soldout"):
        logger.info(
            "[크림통합] 박스/카드팩 신규등록 후보%d — 등록%d 실패%d / "
            "스킵[거래0:%d 굿즈:%d 품절:%d API실패:%d 옵션없음:%d 원가상한:%d 정책:%d "
            "미검출:%d 재게시:%d 실패쿨:%d 이행대기:%d 상한:%d] (%s)",
            box_rs["cand"],
            box_rs["post"],
            box_rs["fail"],
            box_rs["trade"],
            box_rs["goods"],
            box_rs["soldout"],
            box_rs["apifail"],
            box_rs["optmiss"],
            box_rs["overcost"],
            box_rs["policy"],
            box_rs["miss"],
            box_rs["recent"],
            box_rs["failed"],
            box_rs["hold"],
            box_rs["capped"],
            "실행ON" if _EXEC_BOX_RESTOCK else "섀도",
        )
        _emit_autotune_log(
            "KREAM",
            "",
            f"[박스/카드팩] 신규등록 후보 {box_rs['cand']:,} — 등록 {box_rs['post']:,}"
            f"{_fail_tag(box_rs['fail'])} / 거래0 {box_rs['trade']:,}"
            f" 품절 {box_rs['soldout']:,} 옵션없음 {box_rs['optmiss']:,}"
            f" ({'실행ON' if _EXEC_BOX_RESTOCK else '섀도'})",
        )

    # ── [C] 만료 회수(재입찰) — 신발/박스/카드. live 목록서 사라진 만료건 재입찰.
    # [2026-08-05] 등록 실패/스킵 상세 — 카운터만으로는 "왜 안 붙었나"를 알 수 없어
    # 상품 하나씩 파봐야 했다. 사유별 실제 건을 남겨 다음 사이클에 바로 추적한다.
    if _g_optmiss:
        _om = list(_g_optmiss.items())[:15]
        logger.info(
            "[크림통합] 옵션매칭실패 %d건 — 상위: %s",
            len(_g_optmiss),
            " | ".join(f"{k} → 크림[{v[:60]}]" for k, v in _om),
        )
    if _g_skip_samples:
        for _rs, _lst in _g_skip_samples.items():
            logger.info("[크림통합] 스킵사유 %s — 샘플: %s", _rs, ", ".join(_lst))
    # [2026-08-05] 등록 후보에서 빠진 사유 **총계**. 종전엔 샘플 8건만 찍혀
    # "몇 건이 왜 빠졌는지" 를 알 수 없었고, 아예 안 찍히는 경로(비카드 조회 상한 등)가
    # 수천 건을 조용히 삼켰다. 여기서 전량이 사유별로 드러난다.
    if _g_drop:
        logger.info(
            "[크림통합] 등록제외 사유별 총계 — %s",
            " / ".join(
                f"{k}:{v:,}" for k, v in sorted(_g_drop.items(), key=lambda x: -x[1])
            ),
        )
    logger.info("[크림통합] STAGE 만료회수 시작 %.0f초경과", _stage_t.time() - _t_stage)
    expired = await _process_expired_asks(asks, h, rate, tariff_threshold)
    if expired.get("total"):
        logger.info(
            "[크림통합] 만료회수 %d(재입찰후보%d) — 등록%d 실패%d / 스킵[매핑없음%d 오니츠카%d 품절%d 상한%d 가드%d]",
            expired["total"],
            expired["cand"],
            expired["post"],
            expired["fail"],
            expired["nomap"],
            expired["onitsuka"],
            expired["nocost"],
            expired["overcost"],
            expired["guard"],
        )
        _emit_autotune_log(
            "KREAM",
            "",
            f"[만료회수] 만료 {expired['total']:,} 재입찰후보 {expired['cand']:,} — "
            f"등록 {expired['post']:,}{_fail_tag(expired['fail'])} "
            f"(품절{expired['nocost']:,} 상한{expired['overcost']:,} 가드{expired['guard']:,})",
        )
        if _EXECUTE and (expired["post"] or expired["fail"]):
            await _save_setting_map(_SET_RECENT, _g_recent_posts)
            await _save_setting_map(_SET_FAILED, _g_failed_posts)
        # 슬랙/완료로그 집계 합산 — 만료 재입찰도 신규등록으로 표기.
        registered_lines.extend(expired["lines"])
        exec_post += expired["post"]
        exec_fail += expired["fail"]

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
        f"복귀{exec_revert:,}{_fail_tag(exec_fail)} (리스톡탐색 {min(_unified_offset, rest_total):,}/{rest_total:,})",
    )
    await _flush_logs_to_db()
    await _write_back_db_options(db_updates)  # 실시간 원가/재고 → DB 되쓰기
    # 활성사이클 표시용 — 진행/총을 '이번 사이클 처리수'로 통일(가격변동≤진행 정합).
    # 리스톡탐색 offset(3000/23813)은 사이클 완료 로그에 별도 표기(활성사이클 idx 와 혼동 방지).
    _processed = counts["products"] + box.get("total", 0) + shoe.get("total", 0)
    # 진행 = 리스톡탐색 로테이션 위치(offset/전체) — 매 사이클 100% 로 뜨던 오해 제거.
    # 재고변화 = 리스톡(신규재고)+삭제(품절) 실제 건수 — 전에 processed(전량)를 재고로 잘못 표시.
    _stock_chg = (
        counts["restock"]
        + counts["delete"]
        + box.get("delete", 0)
        + shoe.get("delete", 0)
    )
    await _save_kream_cycle_status(
        int(min(_unified_offset, rest_total)),  # idx = 리스톡탐색 진행
        int(rest_total or _processed),  # total = 리스톡 대상 총수
        counts["renew"] + box.get("renew", 0) + shoe.get("renew", 0),  # 가격변동
        counts["delete"] + box.get("delete", 0) + shoe.get("delete", 0),
        processed=_processed,
        cycle_sec=_tstart.time() - _cycle_t0,
        stock_cnt=_stock_chg,
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
    # 카드/박스/카드팩 분리 [2026-07-28] — 카드=PSA옵션, 박스·카드팩은 옵션형식(해외배송(N개))이
    # 동일해 상품명으로 구분.
    # [2026-07-30 집계버그 수정] 기존 `팩\b` 정규식이 "확장팩 … 박스" / "부스터 팩 … 박스"를
    # 카드팩으로 분류해 박스 칸이 영구 0/0으로 찍혔다(실제 박스 7건 입찰 중이었음).
    #  → 이름에 "박스"가 있으면 박스로 우선 판정.
    # 또 옵션 "ONE SIZE"로 박힌 TCG 박스(예: 랜덤박스·덱 더블박스) 2건이 other로 빠져
    # 카드·박스·카드팩 합이 라이브 입찰수와 안 맞았다 → 이름에 박스/팩 있으면 같이 집계.
    # (ONE SIZE 의류·시계를 끌어오지 않도록 이름 키워드 조건 필수)
    def _ask_kind(a):
        opt = str(a.get("option") or "")
        if "PSA" in opt.upper():
            return "card"
        nm = str(a.get("product_name_kr") or a.get("product_name") or "")
        # [2026-08-03] 밀봉 판정을 밀봉 kid 집합(스니덩크 수량옵션 1個/パック 기준)으로 교체.
        # 이름만 보던 기존 방식은 ONE SIZE 로 박힌 밀봉품을 의류 칸으로 흘렸다.
        # 굿즈(플레이매트·슬리브)는 밀봉품이 아니므로 박스/카드팩 칸에서 빼고 잡화로 보낸다.
        _tcg_sealed = (
            "해외배송" in opt or str(a.get("product_id") or "") in _sealed_kids
        ) and not _GOODS_NAME_RE.search(nm)
        if _tcg_sealed:
            if "박스" in nm:
                return "box"
            return "pack" if re.search(r"카드팩|부스터팩|팩", nm) else "box"
        # 신발(mm 사이즈 '245') / 의류·시계·잡화(S/M/L·FREE 등)
        if _SHOE_OPT_RE.fullmatch(opt.strip()):
            return "shoe"
        return "apparel"

    _card_asks = [a for a in asks if _ask_kind(a) == "card"]
    _box_asks = [a for a in asks if _ask_kind(a) == "box"]
    _pack_asks = [a for a in asks if _ask_kind(a) == "pack"]
    _shoe_asks_r = [a for a in asks if _ask_kind(a) == "shoe"]
    _apparel_asks_r = [a for a in asks if _ask_kind(a) == "apparel"]
    _r1c, _n1c, _gtc, _ncc = _rank_summary(_card_asks)
    _r1b, _n1b, _gtb, _ncb = _rank_summary(_box_asks)
    _r1p, _n1p, _gtp, _ncp = _rank_summary(_pack_asks)
    _r1s, _n1s, _gts, _ncs = _rank_summary(_shoe_asks_r)
    _r1a, _n1a, _gta, _nca = _rank_summary(_apparel_asks_r)
    _r1, _n1, _gt, _nc = _rank_summary(asks)
    _ask_kids = {str(a.get("product_id") or "") for a in asks}
    _mapped = len([k for k in _ask_kids if k in kid_to_snkr])
    # [2026-08-02] 신발 삭제(shoe["del"])가 빠져 "삭제 1건"으로 과소표기되던 것 수정.
    _del_all = exec_del + int(box.get("del", 0)) + int(shoe.get("del", 0))
    _upd_all = exec_patch + int(box.get("patch", 0)) + int(shoe.get("patch", 0))
    _fail_all = exec_fail + int(box.get("fail", 0)) + int(shoe.get("fail", 0))
    # 이번 사이클 리스톡 발견(무재고→재고 감지) — 등록 통과/보류 분리 표기.
    _rs_found = int(counts["restock"])
    _rs_hold = max(0, _rs_found - int(rs["ok"]))
    # [2026-08-06] cat1 미등록 수·재고 세부 집계 제거 — 슬랙에서 뺐는데 계산만 남아
    # 매 사이클 전수 쿼리를 돌리고 있었다(제외 사유 총계가 같은 정보를 더 정확히 준다).
    # [2026-08-06] 리스톡 섹션 간결화 — 중복 지표(cat1 미등록 수, 재고 세부)를 걷고
    # '스캔 진행 / 등록 결과 / 제외 사유 / 브랜드 등록률' 로 줄인다.
    _drop_top = " · ".join(
        f"{k} {v:,}" for k, v in sorted(_g_drop.items(), key=lambda kv: -kv[1])[:4]
    )
    _brand_rates, _brand_zero = await _brand_reg_rates()
    _restock_sec = (
        f"━━ 리스톡  스캔 {min(_unified_offset, rest_total):,}/{rest_total:,}"
        f" (이번 {len(rest_slice):,} · 재고보유 우선)\n"
        f"   발견 {_rs_found:,} → 등록 {exec_post:,} · 실패 {exec_fail:,}"
        f" · 보류 {_rs_hold:,}"
    )
    if _drop_top:
        _restock_sec += f"\n   제외  {_drop_top}"
    if _brand_rates:
        _restock_sec += f"\n━━ 브랜드 입찰/재고매칭 상품수  {_brand_rates}"
    # 재고가 있는데 입찰이 통째로 0인 브랜드 — 퍼센트 줄에 묻히면 며칠씩 방치된다.
    if _brand_zero:
        _restock_sec += f"\n   ⚠️ 입찰 0건  {_brand_zero}"
    # [2026-08-06] 개별 등록 상품 나열 제거 — 슬랙에서 건별 확인은 하지 않는데
    # 10줄 + '외 N건' 이 메시지의 절반을 먹었다. 총계만 남긴다.
    # 박스/카드팩 신규등록 — 카드 리스톡과 경로가 달라 별도 줄로 노출(누락 감시).
    if box_rs.get("cand") or box_rs.get("post"):
        _restock_sec += (
            f"\n박스/카드팩 등록 후보 {int(box_rs['cand']):,}건"
            f" — 등록 {int(box_rs['post']):,} · 실패 {int(box_rs['fail']):,}"
            f" ({'실행ON' if _EXEC_BOX_RESTOCK else '섀도'})"
        )
    # [2026-08-05] 실제 반영 재조회 — "반영후"가 산술 계산(시작-삭제+등록)이라
    # 등록이 200 을 받고도 실제로 안 붙은 분(실측 1,193건)이 통째로 가려졌다.
    # 예상과 실제를 나란히 찍어 유실을 드러낸다. 6시간 사이클에 조회 2분은 무시 가능.
    _after_n = None
    try:
        _after_n = len(await _fetch_live_asks(h))
    except Exception as _e:
        logger.info("[크림통합] 반영후 재조회 실패(무시): %s", str(_e)[:60])
    _restock_sec += "\n━━━━━━━━━━\n"
    _msg = (
        f"[크림 입찰갱신]\n"
        f"환율 {rate:.4f} JPY→KRW\n\n"
        # 시작 시점 입찰수만 찍으면 "2,000 지웠는데 왜 그대로냐"로 읽힌다 —
        # 삭제 결과는 다음 사이클 조회에야 반영되므로 반영후 잔여를 같이 표기.
        f"입찰 {len(asks):,}건(시작) → 예상 {max(0, len(asks) - _del_all + exec_post):,}"
        + (
            f" / 실제 {_after_n:,}"
            + (
                f" ⚠️유실 {max(0, len(asks) - _del_all + exec_post) - _after_n:,}"
                if _after_n < max(0, len(asks) - _del_all + exec_post)
                else ""
            )
            if _after_n is not None
            else ""
        )
        + f" | 매핑 {_mapped:,}/{len(_ask_kids):,}건\n"
        f"삭제 {_del_all:,}건(실행) | 조정 {_upd_all:,}건"
        + (f" | ❌실행실패 {_fail_all:,}건(등록포함)" if _fail_all else "")
        # 비1순위도 시작 시점 집계 — 이번 사이클 가격열위 삭제분을 뺀 값을 같이 보여준다
        + f"\n1순위(국내포함) {_r1:,} / 비1순위 {_n1:,}"
        + (f" → {max(0, _n1 - _del_all):,}(삭제반영후)" if _del_all else "")
        + f" (그룹 {_gt:,})\n"
        f"  카드 1순위 {_r1c:,}/{_gtc:,} · 박스 {_r1b:,}/{_gtb:,} · 카드팩 {_r1p:,}/{_gtp:,}\n"
        f"  신발 1순위 {_r1s:,}/{_gts:,} · 의류/잡화 {_r1a:,}/{_gta:,}\n"
        f"무경쟁 후보(국내없음·내입찰연속) {_nc:,}그룹"
        f" (카드{_ncc:,}·박스{_ncb:,}·카드팩{_ncp:,}·신발{_ncs:,}·의류{_nca:,})"
    )
    # 갱신실패 사유 breakdown — 실패 건수만 보이고 원인을 몰라 대응 못 하던 것 보완(로컬 포맷).
    if _fail_reasons:
        _top = sorted(_fail_reasons.items(), key=lambda kv: -kv[1])[:5]
        _msg += "\n\n⚠️ 갱신실패 사유:\n  " + "\n  ".join(
            f"{k}: {v:,}건" for k, v in _top
        )
    if counts["anomaly"]:
        _msg += f"\n\n⚠️ 이상감지(가격오류 의심·갱신차단) {counts['anomaly']:,}건"
    # 가격열위(국내못이김/1등불가) 삭제 — 사이클당 상한(_PRICE_DEL_CAP) 점진 삭제 진행상황.
    _pdskip = (
        counts.get("price_del_skip", 0)
        + int(box.get("price_del_skip", 0))
        + int(shoe.get("price_del_skip", 0))
    )
    _pddone = max(0, _PRICE_DEL_CAP - _price_del_left)
    if _pddone or _pdskip:
        _msg += (
            f"\n\n🧹 가격열위 삭제(2등·국내못이김) {_pddone:,}건"
            f"/사이클상한 {_PRICE_DEL_CAP:,}"
            + (f" · 대기 {_pdskip:,}건(다음 사이클)" if _pdskip else "")
        )
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
