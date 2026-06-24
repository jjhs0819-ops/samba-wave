"""
롯데온·SSG 나이키 상품 중 배경제거 미완료 상품을 자동으로 bg-job에 등록.
매일 새벽 3시 Windows 작업 스케줄러로 실행 (install_night_nike_bg.bat 참조).

실행: python night_nike_bg_enqueue.py
설정: bg_worker.env 에 WORKER_TOKEN이 있으면 별도 로그인 불필요.
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
WORKER_TOKEN = os.environ.get("WORKER_TOKEN", "")


async def main() -> None:
    log.info("=" * 60)
    log.info(
        f"나이키 배경제거 야간 배치 시작 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    log.info("=" * 60)

    if not WORKER_TOKEN:
        log.error("bg_worker.env에 WORKER_TOKEN이 없습니다.")
        sys.exit(1)

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{SAMBA_API_URL}/api/v1/samba/proxy/bg-jobs/enqueue-nike-bg",
            headers={"X-Worker-Token": WORKER_TOKEN},
        )
        resp.raise_for_status()
        data = resp.json()

    if not data.get("success"):
        log.error(f"실패: {data.get('message')}")
        sys.exit(1)

    total = data.get("total", 0)
    job_ids = data.get("job_ids", [])
    log.info(f"완료: {total:,}개 상품 → {len(job_ids)}개 job 등록")
    for jid in job_ids:
        log.info(f"  job_id={jid}")
    log.info("야간 배치 완료.")


if __name__ == "__main__":
    asyncio.run(main())
