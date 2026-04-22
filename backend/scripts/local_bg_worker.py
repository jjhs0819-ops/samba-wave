"""
삼바웨이브 로컬 배경제거 워커
- 5초마다 백엔드에서 배경제거 작업을 가져와 로컬에서 처리
- rembg로 배경제거 → R2 업로드 → 백엔드에 완료 보고
- 실행: python local_bg_worker.py
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import time
import uuid
from pathlib import Path

import boto3
import httpx
from PIL import Image

# ── 환경변수 ──────────────────────────────────────────────
SAMBA_API_URL = os.environ.get("SAMBA_API_URL", "https://api.samba-wave.com")
SAMBA_TOKEN = os.environ.get("SAMBA_TOKEN", "")  # Bearer 토큰
R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY = os.environ.get("R2_ACCESS_KEY", "")
R2_SECRET_KEY = os.environ.get("R2_SECRET_KEY", "")
R2_BUCKET = os.environ.get("R2_BUCKET", "")
R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "")  # https://cdn.example.com
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "5"))  # 초

# .env 파일 자동 로드
_env_file = Path(__file__).parent / "bg_worker.env"
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())
    # 재적용
    SAMBA_API_URL = os.environ.get("SAMBA_API_URL", SAMBA_API_URL)
    SAMBA_TOKEN = os.environ.get("SAMBA_TOKEN", SAMBA_TOKEN)
    R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", R2_ACCOUNT_ID)
    R2_ACCESS_KEY = os.environ.get("R2_ACCESS_KEY", R2_ACCESS_KEY)
    R2_SECRET_KEY = os.environ.get("R2_SECRET_KEY", R2_SECRET_KEY)
    R2_BUCKET = os.environ.get("R2_BUCKET", R2_BUCKET)
    R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", R2_PUBLIC_URL)

# ── rembg 세션 (1회 로드 후 캐시) ──────────────────────────
_rembg_session = None

def get_rembg_session():
    global _rembg_session
    if _rembg_session is None:
        print("[워커] rembg 모델 로딩 중... (최초 1회, 30초 내외)")
        from rembg import new_session
        _rembg_session = new_session("silueta")
        print("[워커] rembg 모델 로딩 완료")
    return _rembg_session


# ── R2 업로드 ─────────────────────────────────────────────
def upload_to_r2(image_bytes: bytes, filename: str) -> str | None:
    if not all([R2_ACCOUNT_ID, R2_ACCESS_KEY, R2_SECRET_KEY, R2_BUCKET]):
        return None
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY,
            region_name="auto",
        )
        key = f"transformed/{filename}"
        s3.put_object(
            Bucket=R2_BUCKET,
            Key=key,
            Body=image_bytes,
            ContentType="image/webp",
        )
        return f"{R2_PUBLIC_URL.rstrip('/')}/transformed/{filename}"
    except Exception as e:
        print(f"[워커] R2 업로드 실패: {e}")
        return None


# ── 배경제거 처리 ─────────────────────────────────────────
def remove_background(image_bytes: bytes) -> bytes:
    from rembg import remove

    session = get_rembg_session()
    src = Image.open(io.BytesIO(image_bytes)).convert("RGBA")

    # 1024px 이상이면 리사이즈 (메모리 절약)
    if max(src.size) > 1024:
        ratio = 1024 / max(src.size)
        new_size = (int(src.width * ratio), int(src.height * ratio))
        src = src.resize(new_size, Image.LANCZOS)

    result = remove(src, session=session, alpha_matting=True,
                    alpha_matting_foreground_threshold=240,
                    alpha_matting_background_threshold=10,
                    alpha_matting_erode_size=10)

    # 흰 배경 합성
    bg = Image.new("RGBA", result.size, (255, 255, 255, 255))
    bg.paste(result, mask=result.split()[3])
    final = bg.convert("RGB")

    buf = io.BytesIO()
    final.save(buf, format="WEBP", quality=90)
    return buf.getvalue()


# ── 이미지 1장 처리 ───────────────────────────────────────
async def process_image(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        resp = await client.get(url, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        image_bytes = resp.content

        # CPU에서 배경제거 (동기 작업을 스레드에 위임)
        processed = await asyncio.to_thread(remove_background, image_bytes)

        # R2 업로드
        md5 = hashlib.md5(image_bytes).hexdigest()[:8]
        uid = uuid.uuid4().hex[:6]
        filename = f"ai_{md5}_{uid}.webp"
        new_url = upload_to_r2(processed, filename)
        return new_url
    except Exception as e:
        print(f"[워커]   이미지 처리 실패 ({url[:60]}...): {e}")
        return None


# ── 잡 1건 처리 ───────────────────────────────────────────
async def process_job(job: dict) -> None:
    job_id = job["job_id"]
    scope: dict = job.get("scope", {"thumbnail": True, "additional": False, "detail": False})
    products: list[dict] = job.get("products", [])

    print(f"\n[워커] ▶ 작업 시작: {job_id} ({len(products)}개 상품)")

    headers = {"Authorization": f"Bearer {SAMBA_TOKEN}", "Content-Type": "application/json"}
    results = []

    async with httpx.AsyncClient(
        timeout=30,
        limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
    ) as client:
        for i, prod in enumerate(products, 1):
            pid = prod["product_id"]
            images: list[str] = prod.get("images") or []
            detail_images: list[str] = prod.get("detail_images") or []
            print(f"[워커]   [{i}/{len(products)}] {pid}")

            new_images = list(images)
            new_detail = list(detail_images)
            transformed = 0
            failed = 0

            # 대표이미지 (thumbnail = 첫 번째)
            if scope.get("thumbnail") and images:
                new_url = await process_image(client, images[0])
                if new_url:
                    new_images[0] = new_url
                    transformed += 1
                else:
                    failed += 1

            # 추가이미지 (additional = 나머지)
            if scope.get("additional") and len(images) > 1:
                for j, url in enumerate(images[1:], 1):
                    new_url = await process_image(client, url)
                    if new_url:
                        new_images[j] = new_url
                        transformed += 1
                    else:
                        failed += 1

            # 상세이미지 (detail)
            if scope.get("detail") and detail_images:
                for j, url in enumerate(detail_images):
                    new_url = await process_image(client, url)
                    if new_url:
                        new_detail[j] = new_url
                        transformed += 1
                    else:
                        failed += 1

            results.append({
                "product_id": pid,
                "success": transformed > 0,
                "new_images": new_images,
                "new_detail_images": new_detail,
                "transformed_count": transformed,
            })
            status = f"완료 {transformed}장" if transformed > 0 else "실패"
            print(f"[워커]   [{i}/{len(products)}] {pid} → {status}")

    # 완료 보고
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{SAMBA_API_URL}/api/v1/samba/proxy/bg-jobs/{job_id}/complete",
                headers=headers,
                json={"results": results},
            )
            resp.raise_for_status()
        success_count = sum(1 for r in results if r["success"])
        print(f"[워커] ✓ 완료 보고: 성공 {success_count}/{len(products)}개")
    except Exception as e:
        print(f"[워커] ✗ 완료 보고 실패: {e}")


# ── 메인 폴링 루프 ────────────────────────────────────────
async def main() -> None:
    print("=" * 50)
    print("삼바웨이브 로컬 배경제거 워커")
    print(f"API: {SAMBA_API_URL}")
    print(f"폴링 간격: {POLL_INTERVAL}초")
    print("종료: Ctrl+C")
    print("=" * 50)

    if not SAMBA_TOKEN:
        print("\n[오류] SAMBA_TOKEN이 설정되지 않았습니다.")
        print("scripts/.env 파일을 확인하세요.")
        return

    headers = {"Authorization": f"Bearer {SAMBA_TOKEN}"}

    while True:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{SAMBA_API_URL}/api/v1/samba/proxy/bg-jobs/next",
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

            job = data.get("job")
            if job:
                await process_job(job)
            else:
                print(f"[워커] 대기 중... ({time.strftime('%H:%M:%S')})", end="\r")

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                print("\n[오류] 인증 실패 — SAMBA_TOKEN을 확인하세요.")
                await asyncio.sleep(30)
            else:
                print(f"\n[워커] API 오류: {e}")
                await asyncio.sleep(POLL_INTERVAL)
        except Exception as e:
            print(f"\n[워커] 연결 오류: {e}")
            await asyncio.sleep(POLL_INTERVAL)
        else:
            if not job:
                await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[워커] 종료됨")
