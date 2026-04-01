"""소싱처/마켓 헬스체크 모듈.

소싱처 1건 수집 시도 + 마켓 인증 테스트로 구조 변경/차단을 감지한다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from backend.utils.logger import logger


@dataclass
class ProbeResult:
    """단일 probe 결과."""

    site: str
    ok: bool
    latency_ms: int = 0
    missing_fields: list[str] = field(default_factory=list)
    error: Optional[str] = None
    checked_at: str = ""


# 소싱처 probe 대상 — 알려진 상품번호 + 기대 필드
PROBE_TARGETS: dict[str, dict[str, Any]] = {
    "MUSINSA": {
        "goods_no": "4746833",
        "expected_fields": ["goodsPrice", "goodsNm", "category"],
    },
}

# 마켓 probe — 인증 테스트만 (상품 등록 안 함)
MARKET_PROBES: list[str] = [
    "smartstore",
    "coupang",
    "11st",
    "lotteon",
    "ssg",
    "lottehome",
    "gsshop",
    "ebay",
    "lazada",
    "qoo10",
    "shopee",
    "shopify",
    "zoom",
]


async def probe_source(site: str) -> ProbeResult:
    """소싱처 1건 수집 시도 → 응답 구조 검증."""
    target = PROBE_TARGETS.get(site)
    if not target:
        return ProbeResult(
            site=site,
            ok=False,
            error="probe 대상 미설정",
            checked_at=datetime.now(timezone.utc).isoformat(),
        )

    start = time.monotonic()
    try:
        if site == "MUSINSA":
            from backend.domain.samba.proxy.musinsa import MusinsaClient, RateLimitError

            client = MusinsaClient()
            try:
                detail = await client.get_goods_detail(target["goods_no"])
            except RateLimitError as e:
                elapsed = int((time.monotonic() - start) * 1000)
                return ProbeResult(
                    site=site,
                    ok=False,
                    latency_ms=elapsed,
                    error=f"차단: HTTP {e.status}",
                    checked_at=datetime.now(timezone.utc).isoformat(),
                )

            elapsed = int((time.monotonic() - start) * 1000)

            # 기대 필드 검증
            missing = []
            raw_data = detail  # get_goods_detail은 변환된 dict 반환
            for field_name in target.get("expected_fields", []):
                # 변환된 결과에서 주요 필드 확인
                check_map = {
                    "goodsPrice": "salePrice",
                    "goodsNm": "name",
                    "category": "category",
                }
                mapped = check_map.get(field_name, field_name)
                if not raw_data.get(mapped):
                    missing.append(field_name)

            return ProbeResult(
                site=site,
                ok=len(missing) == 0,
                latency_ms=elapsed,
                missing_fields=missing,
                checked_at=datetime.now(timezone.utc).isoformat(),
            )
        else:
            return ProbeResult(
                site=site,
                ok=False,
                error="probe 미구현",
                checked_at=datetime.now(timezone.utc).isoformat(),
            )
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        return ProbeResult(
            site=site,
            ok=False,
            latency_ms=elapsed,
            error=str(exc),
            checked_at=datetime.now(timezone.utc).isoformat(),
        )


async def probe_market(market_type: str, session: Any) -> ProbeResult:
    """마켓 인증 테스트 → API 접근 가능 여부 확인."""
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository

    start = time.monotonic()
    try:
        repo = SambaSettingsRepository(session)
        row = await repo.find_by_async(key=f"store_{market_type}")
        if not row or not row.value:
            elapsed = int((time.monotonic() - start) * 1000)
            return ProbeResult(
                site=market_type,
                ok=False,
                latency_ms=elapsed,
                error="설정 없음",
                checked_at=datetime.now(timezone.utc).isoformat(),
            )

        creds = row.value
        if not isinstance(creds, dict):
            elapsed = int((time.monotonic() - start) * 1000)
            return ProbeResult(
                site=market_type,
                ok=False,
                latency_ms=elapsed,
                error="설정 형식 오류",
                checked_at=datetime.now(timezone.utc).isoformat(),
            )

        # 마켓별 인증 테스트
        ok = False
        error_msg = None

        if market_type == "smartstore":
            from backend.domain.samba.proxy.smartstore import SmartStoreClient

            client_id = creds.get("clientId", "")
            client_secret = creds.get("clientSecret", "")
            if client_id and client_secret:
                client = SmartStoreClient(client_id, client_secret)
                token = await client.get_token()
                ok = bool(token)
                if not ok:
                    error_msg = "토큰 발급 실패"
            else:
                error_msg = "Client ID/Secret 미설정"

        elif market_type == "coupang":
            from backend.domain.samba.proxy.coupang import CoupangClient

            access_key = creds.get("accessKey", "")
            secret_key = creds.get("secretKey", "")
            if access_key and secret_key:
                client = CoupangClient(access_key, secret_key)
                ok = await client.test_auth()
            else:
                error_msg = "Access/Secret Key 미설정"

        elif market_type == "11st":
            from backend.domain.samba.proxy.elevenst import ElevenstClient

            api_key = creds.get("apiKey", "")
            if api_key:
                client = ElevenstClient(api_key)
                ok = await client.test_auth()
            else:
                error_msg = "API Key 미설정"

        elif market_type == "lotteon":
            from backend.domain.samba.proxy.lotteon import LotteonClient

            api_key = creds.get("apiKey", "")
            if api_key:
                client = LotteonClient(api_key)
                ok = await client.test_auth()
            else:
                error_msg = "API Key 미설정"

        elif market_type == "ssg":
            from backend.domain.samba.proxy.ssg import SSGClient

            api_key = creds.get("apiKey", "")
            if api_key:
                client = SSGClient(api_key)
                ok = await client.test_auth()
            else:
                error_msg = "API Key 미설정"

        else:
            # 기타 마켓은 설정 존재 여부만 확인
            ok = bool(creds)

        elapsed = int((time.monotonic() - start) * 1000)
        return ProbeResult(
            site=market_type,
            ok=ok,
            latency_ms=elapsed,
            error=error_msg,
            checked_at=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        return ProbeResult(
            site=market_type,
            ok=False,
            latency_ms=elapsed,
            error=str(exc),
            checked_at=datetime.now(timezone.utc).isoformat(),
        )


async def run_all_probes(session: Any) -> dict[str, Any]:
    """전체 소싱처+마켓 probe → 결과 반환."""
    import asyncio

    results: dict[str, Any] = {"sources": {}, "markets": {}}

    # 소싱처 probe
    for site in PROBE_TARGETS:
        r = await probe_source(site)
        results["sources"][site] = {
            "ok": r.ok,
            "latency_ms": r.latency_ms,
            "missing_fields": r.missing_fields,
            "error": r.error,
            "checked_at": r.checked_at,
        }

    # 마켓 probe (병렬)
    async def _probe_market(mt: str):
        return mt, await probe_market(mt, session)

    tasks = [_probe_market(mt) for mt in MARKET_PROBES]
    market_results = await asyncio.gather(*tasks, return_exceptions=True)

    for item in market_results:
        if isinstance(item, Exception):
            continue
        mt, r = item
        results["markets"][mt] = {
            "ok": r.ok,
            "latency_ms": r.latency_ms,
            "error": r.error,
            "checked_at": r.checked_at,
        }

    # samba_settings에 결과 저장
    try:
        from backend.domain.samba.forbidden.repository import SambaSettingsRepository

        repo = SambaSettingsRepository(session)
        for site, data in results["sources"].items():
            existing = await repo.find_by_async(key=f"probe_{site}")
            if existing:
                existing.value = data
                session.add(existing)
            else:
                from backend.domain.samba.forbidden.model import SambaSettings

                session.add(SambaSettings(key=f"probe_{site}", value=data))

        for mt, data in results["markets"].items():
            existing = await repo.find_by_async(key=f"probe_market_{mt}")
            if existing:
                existing.value = data
                session.add(existing)
            else:
                from backend.domain.samba.forbidden.model import SambaSettings

                session.add(SambaSettings(key=f"probe_market_{mt}", value=data))

        await session.commit()
    except Exception as exc:
        logger.warning(f"[probe] 결과 저장 실패: {exc}")

    return results
