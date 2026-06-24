"""
롯데온·SSG 나이키 상품 중 배경제거 미완료 상품을 자동으로 bg-job에 등록.
매일 새벽 3시 Windows 작업 스케줄러로 실행 (install_night_nike_bg.bat 참조).

실행: python night_nike_bg_enqueue.py
설정: bg_worker.env 에 SAMBA_EMAIL / SAMBA_PASSWORD 추가
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import httpx

# ── 로그 설정 ──────────────────────────────────────────────
_LOG_DIR = Path(__file__).parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_LOG_FILE = _LOG_DIR / "night_nike_bg.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(_LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── bg_worker.env 로드 ─────────────────────────────────────
_env_file = Path(__file__).parent / "bg_worker.env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            k, _, v = _line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

SAMBA_API_URL = os.environ.get("SAMBA_API_URL", "https://api.samba-wave.co.kr")
SAMBA_EMAIL = os.environ.get("SAMBA_EMAIL", "")
SAMBA_PASSWORD = os.environ.get("SAMBA_PASSWORD", "")

# 배경제거 대상 소싱처
TARGET_SITES = ["LOTTEON", "SSG"]
# 배경제거 범위 (thumbnail만)
BG_SCOPE = {"thumbnail": True, "additional": False, "detail": False, "skip_processed": True}
# 브랜드 검색어 (ilike 패턴 — 한국어+영어 둘 다)
BRAND_QUERIES = ["나이키", "nike"]


async def login(client: httpx.AsyncClient) -> str:
    """이메일/비번으로 로그인 → JWT 토큰 반환."""
    if not SAMBA_EMAIL or not SAMBA_PASSWORD:
        raise RuntimeError(
            "bg_worker.env에 SAMBA_EMAIL / SAMBA_PASSWORD를 추가해주세요."
        )
    resp = await client.post(
        f"{SAMBA_API_URL}/api/v1/samba/users/login",
        json={"email": SAMBA_EMAIL, "password": SAMBA_PASSWORD},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token", "")
    if not token:
        raise RuntimeError(f"로그인 실패: {data}")
    log.info(f"로그인 성공: {SAMBA_EMAIL}")
    return token


async def fetch_product_ids(client: httpx.AsyncClient, token: str) -> list[str]:
    """LOTTEON+SSG 나이키 상품 중 배경제거 미완료 ID 목록 조회."""
    headers = {"Authorization": f"Bearer {token}"}
    all_ids: set[str] = set()

    for site in TARGET_SITES:
        for brand_q in BRAND_QUERIES:
            skip = 0
            page_limit = 10000
            while True:
                resp = await client.get(
                    f"{SAMBA_API_URL}/api/v1/samba/collector/products/scroll",
                    headers=headers,
                    params={
                        "source_site": site,
                        "search": brand_q,
                        "search_type": "brand",
                        "ai_filter": "ai_img_no",
                        "ids_only": "true",
                        "skip": skip,
                        "limit": page_limit,
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                ids: list[str] = data.get("ids", [])
                total: int = data.get("total", 0)
                all_ids.update(ids)
                log.info(
                    f"  [{site}][{brand_q}] skip={skip} → {len(ids)}개 (전체 {total}개)"
                )
                if not ids or skip + len(ids) >= total:
                    break
                skip += page_limit

    return list(all_ids)


async def enqueue_bg_job(
    client: httpx.AsyncClient, token: str, product_ids: list[str]
) -> str | None:
    """배경제거 bg-job 등록 → job_id 반환."""
    resp = await client.post(
        f"{SAMBA_API_URL}/api/v1/samba/proxy/images/transform",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "product_ids": product_ids,
            "scope": BG_SCOPE,
            "mode": "background",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        log.warning(f"bg-job 등록 실패: {data.get('message')}")
        return None
    job_id = data.get("job_id")
    log.info(f"bg-job 등록 완료: job_id={job_id}, 상품 {len(product_ids)}개")
    return job_id


async def main() -> None:
    log.info("=" * 60)
    log.info(f"나이키 배경제거 야간 배치 시작 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"대상 소싱처: {TARGET_SITES}")
    log.info("=" * 60)

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            token = await login(client)
        except Exception as e:
            log.error(f"로그인 실패: {e}")
            sys.exit(1)

        log.info("배경제거 미완료 나이키 상품 조회 중...")
        try:
            product_ids = await fetch_product_ids(client, token)
        except Exception as e:
            log.error(f"상품 조회 실패: {e}")
            sys.exit(1)

        if not product_ids:
            log.info("처리할 상품 없음 — 모두 변환 완료 또는 해당 상품 없음.")
            return

        log.info(f"처리 대상: {len(product_ids):,}개 상품")

        # 한 번에 최대 5,000개씩 분할 등록 (너무 많으면 단일 job이 너무 커질 수 있음)
        BATCH = 5000
        chunks = [product_ids[i:i + BATCH] for i in range(0, len(product_ids), BATCH)]
        log.info(f"분할 등록: {len(chunks)}개 배치 (최대 {BATCH:,}개/배치)")

        for idx, chunk in enumerate(chunks, 1):
            log.info(f"배치 {idx}/{len(chunks)} 등록 ({len(chunk):,}개)...")
            try:
                job_id = await enqueue_bg_job(client, token, chunk)
                if job_id:
                    log.info(f"  → job_id={job_id}")
            except Exception as e:
                log.error(f"  → 배치 {idx} 등록 실패: {e}")

    log.info("야간 배치 완료.")


if __name__ == "__main__":
    asyncio.run(main())
