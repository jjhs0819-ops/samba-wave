"""
Samba Wave Local BG Worker
- Polls backend every 5s for pending background removal jobs
- Runs rembg locally -> uploads to R2 -> reports completion
- Run: python local_bg_worker.py
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import time
import uuid
from pathlib import Path

import httpx
from PIL import Image

# ── Load bg_worker.env ───────────────────────────────────
_env_file = Path(__file__).parent / "bg_worker.env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            k, _, v = _line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

SAMBA_API_URL = os.environ.get("SAMBA_API_URL", "https://api.samba-wave.co.kr")
WORKER_TOKEN = os.environ.get("WORKER_TOKEN") or os.environ.get("BG_WORKER_TOKEN", "")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "5"))

HEADERS = {"X-Worker-Token": WORKER_TOKEN}

# ── R2 config (fetched from API at startup) ───────────────
_r2: dict = {}

# ── rembg session (loaded once, reused) ──────────────────
_rembg_session = None


def get_rembg_session():
    global _rembg_session
    if _rembg_session is None:
        print("[Worker] Loading rembg model... (first time only, ~30s)")
        from rembg import new_session

        _rembg_session = new_session("silueta")
        print("[Worker] rembg model loaded.")
    return _rembg_session


# ── R2 upload ────────────────────────────────────────────
def upload_to_r2(image_bytes: bytes, filename: str) -> str | None:
    if not _r2.get("bucket"):
        return None
    try:
        import boto3

        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{_r2['account_id']}.r2.cloudflarestorage.com",
            aws_access_key_id=_r2["access_key"],
            aws_secret_access_key=_r2["secret_key"],
            region_name="auto",
        )
        key = f"transformed/{filename}"
        s3.put_object(
            Bucket=_r2["bucket"], Key=key, Body=image_bytes, ContentType="image/webp"
        )
        return f"{_r2['public_url'].rstrip('/')}/transformed/{filename}"
    except Exception as e:
        print(f"[Worker]   R2 upload failed: {e}")
        return None


# ── Background removal ───────────────────────────────────
def remove_background(image_bytes: bytes) -> bytes:
    from rembg import remove

    session = get_rembg_session()
    src = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    if max(src.size) > 1024:
        ratio = 1024 / max(src.size)
        src = src.resize(
            (int(src.width * ratio), int(src.height * ratio)), Image.LANCZOS
        )

    result = remove(
        src,
        session=session,
        alpha_matting=True,
        alpha_matting_foreground_threshold=240,
        alpha_matting_background_threshold=10,
        alpha_matting_erode_size=10,
    )

    bg = Image.new("RGBA", result.size, (255, 255, 255, 255))
    bg.paste(result, mask=result.split()[3])
    buf = io.BytesIO()
    bg.convert("RGB").save(buf, format="WEBP", quality=90)
    return buf.getvalue()


# ── Process one image URL ─────────────────────────────────
async def process_image(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        resp = await client.get(url, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        processed = await asyncio.to_thread(remove_background, resp.content)
        md5 = hashlib.md5(resp.content).hexdigest()[:8]
        filename = f"ai_{md5}_{uuid.uuid4().hex[:6]}.webp"
        result_url = upload_to_r2(processed, filename)
        if result_url is None:
            print("[Worker]   R2 업로드 실패 — R2 설정(bg_worker.env)을 확인하세요")
        return result_url
    except Exception as e:
        print(f"[Worker]   Image error ({url[:60]}): {e}")
        return None


# ── Process one job ──────────────────────────────────────
async def process_job(job: dict) -> None:
    job_id = job["job_id"]
    scope: dict = job.get(
        "scope", {"thumbnail": True, "additional": False, "detail": False}
    )
    products: list[dict] = job.get("products", [])
    print(f"\n[Worker] Job start: {job_id} ({len(products)} products)")

    results = []
    async with httpx.AsyncClient(
        timeout=30,
        limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
    ) as client:
        for i, prod in enumerate(products, 1):
            pid = prod["product_id"]
            images: list[str] = prod.get("images") or []
            detail_images: list[str] = prod.get("detail_images") or []

            # 처리 대상 이미지 총개수 미리 계산 (사진 인덱스 진행률 표시용)
            img_total = 0
            if scope.get("thumbnail") and images:
                img_total += 1
            if scope.get("additional") and len(images) > 1:
                img_total += len(images) - 1
            if scope.get("detail") and detail_images:
                img_total += len(detail_images)

            print(f"[Worker]   [{i}/{len(products)}] {pid} ({img_total} images)")

            new_images = list(images)
            new_detail = list(detail_images)
            transformed = 0
            img_done = 0

            async def _report_progress(bump_product: bool = False) -> None:
                """사진 단위 진행률 즉시 보고 (실패 무시)."""
                try:
                    await client.patch(
                        f"{SAMBA_API_URL}/api/v1/samba/proxy/bg-jobs/{job_id}/progress",
                        headers=HEADERS,
                        json={
                            "image_current": img_done,
                            "image_total": img_total,
                            "current_product_id": pid,
                            "bump_product": bump_product,
                        },
                    )
                except Exception:
                    pass

            # 시작 직후 0/img_total 한 번 보고 → 프론트 폴링이 곧바로 인식
            await _report_progress(bump_product=False)

            if scope.get("thumbnail") and images:
                url = await process_image(client, images[0])
                if url:
                    new_images[0] = url
                    transformed += 1
                img_done += 1
                await _report_progress(bump_product=False)

            if scope.get("additional") and len(images) > 1:
                for j, orig in enumerate(images[1:], 1):
                    url = await process_image(client, orig)
                    if url:
                        new_images[j] = url
                        transformed += 1
                    img_done += 1
                    await _report_progress(bump_product=False)

            if scope.get("detail") and detail_images:
                for j, orig in enumerate(detail_images):
                    url = await process_image(client, orig)
                    if url:
                        new_detail[j] = url
                        transformed += 1
                    img_done += 1
                    await _report_progress(bump_product=False)

            results.append(
                {
                    "product_id": pid,
                    "success": transformed > 0,
                    "new_images": new_images,
                    "new_detail_images": new_detail,
                    "transformed_count": transformed,
                }
            )
            print(
                f"[Worker]   [{i}/{len(products)}] {pid} -> {transformed} images done"
            )
            # 상품 1건 완료 — current 증가
            await _report_progress(bump_product=True)

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{SAMBA_API_URL}/api/v1/samba/proxy/bg-jobs/{job_id}/complete",
            headers=HEADERS,
            json={"results": results},
        )
        resp.raise_for_status()
    ok = sum(1 for r in results if r["success"])
    print(f"[Worker] Job done: {ok}/{len(products)} succeeded")


# ── Fetch R2 config from API ─────────────────────────────
async def fetch_config() -> bool:
    global _r2, WORKER_TOKEN, HEADERS
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{SAMBA_API_URL}/api/v1/samba/proxy/bg-jobs/config",
                headers=HEADERS,
            )
            resp.raise_for_status()
            data = resp.json()
        if not data.get("success"):
            print(f"[Worker] Config error: {data.get('message')}")
            return False
        # 백엔드가 자동 생성한 토큰을 받아서 사용
        if data.get("worker_token"):
            WORKER_TOKEN = data["worker_token"]
            HEADERS = {"X-Worker-Token": WORKER_TOKEN}
            print("[Worker] 토큰 자동 수신 완료")
        _r2 = data["r2"]
        print(f"[Worker] R2 config loaded: bucket={_r2.get('bucket')}")
        return True
    except Exception as e:
        print(f"[Worker] Config fetch failed: {e}")
        return False


# ── Main polling loop ────────────────────────────────────
async def main() -> None:
    print("=" * 50)
    print("Samba Wave Local BG Worker")
    print(f"API: {SAMBA_API_URL}")
    print(f"Poll interval: {POLL_INTERVAL}s")
    print("Stop: Ctrl+C")
    print("=" * 50)

    print("\n[Worker] Connecting to backend...")
    if not await fetch_config():
        print("[Error] Cannot connect or token is invalid. Check WORKER_TOKEN.")
        return

    while True:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{SAMBA_API_URL}/api/v1/samba/proxy/bg-jobs/next",
                    headers=HEADERS,
                )
                resp.raise_for_status()
                data = resp.json()

            if data.get("error"):
                print(f"\n[Worker] Auth error: {data['error']}")
                await asyncio.sleep(30)
                continue

            job = data.get("job")
            if job:
                await process_job(job)
            else:
                print(f"[Worker] Waiting... ({time.strftime('%H:%M:%S')})", end="\r")
                await asyncio.sleep(POLL_INTERVAL)

        except Exception as e:
            print(f"\n[Worker] Error: {e}")
            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Worker] Stopped.")
