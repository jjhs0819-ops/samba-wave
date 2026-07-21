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

import json
import logging
import math

import httpx
from sqlalchemy import text as _text

from backend.db.orm import get_read_session

logger = logging.getLogger(__name__)

KREAM_OPENAPI_BASE = "https://partner-openapi.kream.co.kr/openapi"
_PER_PAGE = 50  # 공식 스펙 상한(초과 시 조용히 0건)
_COOLDOWN_KEY = "kream_nocomp_cooldown"  # samba_settings 키 — {"pid|opt": epoch}
_COOLDOWN_TTL = 86400  # 24h — 무경쟁 인상 후 밀린 (상품,옵션) 재인상 금지

# 가격정책 — 로컬 _kream_ask_adjust.py POLICY 포팅(동일 기본값). 추후 마진설정 API 로 교체 가능.
POLICY = {
    "min_margin_amount": 9000,
    "competitive_margin_rate": 13,
    "no_competition_margin_rate": 31,
    "shipping_fee_card": 300,  # 스니덩크 배송비(카드) — 엔화
    "shipping_fee_box": 900,  # 스니덩크 배송비(박스) — 엔화
    "forwarding_fee": 8000,  # 배대지비용 — 원
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


def calc_base(
    price_jpy: float, rate: float, is_box: bool = False, is_card: bool = True
) -> float:
    """원가 base = (snkr엔 + 배송엔)×환율 + 배대지비(원). 비카드는 원가 5% 가산."""
    ship_jpy = POLICY["shipping_fee_box"] if is_box else POLICY["shipping_fee_card"]
    eff_jpy = price_jpy * 1.05 if not is_card else price_jpy
    return (eff_jpy + ship_jpy) * rate + POLICY["forwarding_fee"]


def calc_min_price(
    price_jpy: float, rate: float, is_box: bool = False, is_card: bool = True
) -> int:
    base = calc_base(price_jpy, rate, is_box, is_card)
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


async def _jpy_krw_rate() -> float:
    """JPY/KRW 환율 — 환율서비스 이용, 실패 시 기본값."""
    try:
        from backend.domain.samba.exchange_rate_service import get_latest_exchange_rates

        payload = await get_latest_exchange_rates()
        rates = payload.get("rates") if isinstance(payload, dict) else None
        if isinstance(rates, dict) and rates.get("JPY") and rates.get("KRW"):
            return float(rates["KRW"]) / float(rates["JPY"])
    except Exception as exc:
        logger.warning("[크림섀도] 환율 조회 실패, 기본값 사용: %s", exc)
    return 9.12


async def _usd_krw_rate() -> float:
    try:
        from backend.domain.samba.exchange_rate_service import get_latest_exchange_rates

        payload = await get_latest_exchange_rates()
        rates = payload.get("rates") if isinstance(payload, dict) else None
        if isinstance(rates, dict) and rates.get("KRW"):
            return float(rates["KRW"])
    except Exception:
        pass
    return 1387.0


async def _load_snkr_option_prices(pids: set[str]) -> dict[tuple[str, str], int]:
    """(kream_pid, 옵션명) → 스니덩크 원가(JPY). samba_collected_product.options 에서."""
    if not pids:
        return {}
    out: dict[tuple[str, str], int] = {}
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
            if isinstance(o, dict) and o.get("name") and (o.get("price") or 0) > 0:
                out[(str(kid), str(o["name"]))] = int(o["price"])
    return out


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
    price_map = await _load_snkr_option_prices(pids)
    rate = await _jpy_krw_rate()
    tariff_threshold = int(150 * await _usd_krw_rate())

    # [Phase4a] 로컬 _kream_ask_adjust 결정로직 충실 이식 — rank1 유도(price<=lowest) +
    # 5분기(마진미달인상/경쟁추종인상/무경쟁인상/과가격하향/유지) + rank1없음 추종. 로그만, PATCH 없음.
    # (쿨다운 상태저장은 Phase4b, 실제 PATCH·PATCH응답 rank검증은 Phase4c에서)
    from collections import Counter as _Counter

    acts: _Counter = _Counter()
    computed = no_cost = cd_blocked = 0
    samples: list[dict] = []
    for a in asks:
        pid = str(a.get("product_id") or "")
        opt = str(a.get("option") or "")
        cur = int(a.get("price") or 0)
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

        acts[act] += 1
        if act not in ("유지", "유지(동률)") and len(samples) < 10:
            samples.append(
                {"pid": pid, "opt": opt, "cur": cur, "target": target, "act": act}
            )

    summary = {
        "ok": True,
        "live_asks": len(asks),
        "target_computed": computed,
        "actions": dict(acts),
        "cooldown_size": len(cooldown),
        "cooldown_blocked": cd_blocked,
        "no_snkr_cost": no_cost,
        "rate_jpy_krw": round(rate, 3),
        "samples": samples,
    }
    logger.info(
        "[크림섀도] Phase4b — 입찰%d 계산%d / 결정 %s / 쿨다운%d(보류%d) / 원가없음%d (환율 %.2f)",
        summary["live_asks"],
        computed,
        dict(acts),
        len(cooldown),
        cd_blocked,
        no_cost,
        rate,
    )
    if samples:
        logger.info("[크림섀도] 변동 샘플: %s", samples[:5])
    return summary
