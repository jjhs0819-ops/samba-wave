"""크림 갱신·리스톡 백엔드 오토튠 이식 — 섀도모드 [Phase 1, 2026-07-21].

집PC 로컬 루프(_kream_unified_loop.ps1)가 하던 크림 입찰갱신/리스톡을 백엔드로
단계적 이식한다. 프로덕션 오토튠 코어(collector_autotune.py 6,073줄)는 절대 건드리지
않고 이 격리 모듈에서만 동작한다.

Phase 1 (이 파일): 백엔드↔크림 read 경로만 확립.
  - 크림 공식 OpenAPI 인증(samba_market_account) → live asks 조회 → 요약 로그.
  - **쓰기/POST/DB수정 전혀 없음.** 백엔드가 크림 상태를 읽을 수 있는지 증명만.
Phase 2: 가격정책+PSA grade 매핑 포팅 → target 계산(로그만).
Phase 3: 로컬 루프 실제행동과 대조검증.
Phase 4: 검증 후 실제 실행 전환.

활성화: 환경변수 KREAM_SHADOW=1 일 때만 lifecycle 이 주기 호출(기본 off).
"""

import logging

import httpx
from sqlalchemy import text as _text

from backend.db.orm import get_read_session

logger = logging.getLogger(__name__)

KREAM_OPENAPI_BASE = "https://partner-openapi.kream.co.kr/openapi"
_PER_PAGE = 50  # 공식 스펙 상한(초과 시 조용히 0건)


async def _load_kream_creds() -> tuple[str, str, str]:
    """(service, key, secret) — samba_market_account(kream) additional_fields(json)."""
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
        import json

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


async def run_kream_shadow_once() -> dict:
    """Phase 1 섀도 1회 — 크림 live 입찰 조회 후 요약만 로그. 쓰기·POST 없음.

    Returns: 요약 dict (모니터링·대조용).
    """
    service, key, secret = await _load_kream_creds()
    if not (service and key and secret):
        logger.warning("[크림섀도] 인증정보 없음(samba_market_account kream) — 스킵")
        return {"ok": False, "reason": "no_creds"}

    h = _headers(service, key, secret)
    try:
        asks = await _fetch_live_asks(h)
    except Exception as exc:
        logger.warning("[크림섀도] live 입찰 조회 실패: %s", exc)
        return {"ok": False, "reason": f"fetch_error: {exc}"}

    # 옵션 유형별 분포(PSA10/PSA9/해외배송 등) — Phase 2 target 계산 대상 파악용
    from collections import Counter

    by_option = Counter(str(a.get("option") or "?") for a in asks)
    products = {a.get("product_id") for a in asks}
    summary = {
        "ok": True,
        "live_asks": len(asks),
        "distinct_products": len(products),
        "by_option_top": dict(by_option.most_common(8)),
    }
    logger.info(
        "[크림섀도] Phase1 read OK — live입찰 %d건 / 상품 %d개 / 옵션분포 %s",
        summary["live_asks"],
        summary["distinct_products"],
        summary["by_option_top"],
    )
    return summary
