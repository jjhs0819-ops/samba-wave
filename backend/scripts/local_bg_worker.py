"""
Samba Wave Local BG Worker
- Polls backend every 5s for pending watermark removal jobs
- 우상단 영역이 "흰배경 + 로고" 패턴 → PIL 흰박스 (빠름, 95% 케이스)
- 그 외 (사진 컨텐츠 — Jordan/Nike 등) → rembg 전체 배경 제거 (느리지만 정확)
- Run: python local_bg_worker.py
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import threading
import time
import uuid
from pathlib import Path

import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageStat

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
# stuck/잘못 큐잉된 잡을 워커 단에서 즉시 skip하기 위한 화이트아웃 리스트(콤마 구분)
SKIP_JOB_IDS: set[str] = {
    s.strip() for s in os.environ.get("BG_SKIP_JOB_IDS", "").split(",") if s.strip()
}

HEADERS = {"X-Worker-Token": WORKER_TOKEN}

# ── R2 config (fetched from API at startup) ───────────────
_r2: dict = {}


# ── R2 upload ────────────────────────────────────────────
def upload_to_r2(image_bytes: bytes, filename: str) -> str | None:
    """R2 업로드 — 일시 장애 대비 3회 재시도(1.5s/3s 백오프)."""
    if not _r2.get("bucket"):
        return None
    import boto3

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            s3 = boto3.client(
                "s3",
                endpoint_url=f"https://{_r2['account_id']}.r2.cloudflarestorage.com",
                aws_access_key_id=_r2["access_key"],
                aws_secret_access_key=_r2["secret_key"],
                region_name="auto",
            )
            key = f"transformed/{filename}"
            s3.put_object(
                Bucket=_r2["bucket"],
                Key=key,
                Body=image_bytes,
                ContentType="image/webp",
            )
            return f"{_r2['public_url'].rstrip('/')}/transformed/{filename}"
        except Exception as e:
            last_err = e
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    print(f"[Worker]   [upload] R2 업로드 3회 실패: {last_err}")
    return None


# ── Watermark removal ────────────────────────────────────
# 우측 상단 워터마크 박스 비율 (이미지 가로/세로 기준)
_WM_BOX_W_RATIO = 0.22
_WM_BOX_H_RATIO = 0.18
# 영역이 이 값 이상으로 평균 RGB가 밝으면 "워터마크 없음"으로 보고 skip
_WM_NO_LOGO_THRESHOLD = 240
# "흰배경 + 작은 로고" 패턴 판정용 — near-white 픽셀(채널별 ≥230) 비율 기준
_NEAR_WHITE_CHANNEL = 230
_WHITE_BG_LOGO_RATIO = 0.75

# rembg 세션 lazy 캐시 (모델 200MB, 매 호출마다 로드 방지)
_rembg_session = None
_rembg_lock = threading.Lock()


def _get_rembg_session():
    """rembg 세션 1회 생성 후 재사용 (스레드 안전)."""
    global _rembg_session
    if _rembg_session is None:
        with _rembg_lock:
            if _rembg_session is None:
                from rembg import new_session

                _rembg_session = new_session("u2net")
                print("[Worker] rembg 세션 초기화 완료 (u2net)")
    return _rembg_session


def _is_white_background_logo(crop: Image.Image) -> bool:
    """우상단 영역이 '흰배경 + 작은 로고' 패턴인지 판정.

    near-white 픽셀(R/G/B 모두 ≥230) 비율이 75% 이상이면 → 워터마크 케이스.
    그 외(모델/사진 컨텐츠)는 rembg로 처리해야 함.
    """
    pixels = list(crop.getdata())
    if not pixels:
        return False
    near_white = sum(
        1
        for r, g, b in pixels
        if r >= _NEAR_WHITE_CHANNEL
        and g >= _NEAR_WHITE_CHANNEL
        and b >= _NEAR_WHITE_CHANNEL
    )
    return near_white / len(pixels) >= _WHITE_BG_LOGO_RATIO


def _rembg_full(src: Image.Image, *, use_alpha_matting: bool = True) -> bytes:
    """rembg로 전체 배경 제거 후 흰배경 합성 → WEBP 반환.

    use_alpha_matting=False 폴백 모드: 알파매팅 끄면 가장자리 거칠지만 더 안정적.
    """
    from rembg import remove

    buf_in = io.BytesIO()
    src.save(buf_in, format="PNG")
    if use_alpha_matting:
        result = remove(
            buf_in.getvalue(),
            session=_get_rembg_session(),
            alpha_matting=True,
            alpha_matting_foreground_threshold=250,
            alpha_matting_background_threshold=30,
            alpha_matting_erode_size=15,
        )
    else:
        result = remove(buf_in.getvalue(), session=_get_rembg_session())
    out = Image.open(io.BytesIO(result)).convert("RGBA")
    r, g, b, a = out.split()
    a = a.point(lambda x: 0 if x < 20 else x)
    out = Image.merge("RGBA", (r, g, b, a))
    white_bg = Image.new("RGBA", out.size, (255, 255, 255, 255))
    composite = Image.alpha_composite(white_bg, out).convert("RGB")
    buf = io.BytesIO()
    composite.save(buf, format="WEBP", quality=90)
    return buf.getvalue()


def _is_bg_removed(result_bytes: bytes) -> bool:
    """결과 이미지의 가장자리가 충분히 흰색인지 검증.

    rembg 실패 시 결과 가장자리에 원본 배경 색이 그대로 남음 → 흰픽셀 비율로 판정.
    가장자리 픽셀의 85% 이상이 near-white(R/G/B≥240)면 배경제거 성공으로 간주.
    """
    try:
        result = Image.open(io.BytesIO(result_bytes)).convert("RGB")
        w, h = result.size
        # 상하단 1px + 좌우 1px = 가장자리 픽셀
        pixels: list[tuple[int, int, int]] = []
        pixels.extend(result.getpixel((x, 0)) for x in range(0, w, max(1, w // 100)))
        pixels.extend(
            result.getpixel((x, h - 1)) for x in range(0, w, max(1, w // 100))
        )
        pixels.extend(result.getpixel((0, y)) for y in range(0, h, max(1, h // 100)))
        pixels.extend(
            result.getpixel((w - 1, y)) for y in range(0, h, max(1, h // 100))
        )
        if not pixels:
            return False
        white = sum(1 for r, g, b in pixels if r >= 240 and g >= 240 and b >= 240)
        return white / len(pixels) >= 0.85
    except Exception:
        return False


def remove_watermark(image_bytes: bytes) -> bytes | None:
    """우상단 패턴에 따라 분기:
    - 흰배경(워터마크 없음) → 원본 그대로 (변환 불필요로 간주, bytes 반환)
    - 흰배경 + 로고 패턴 → PIL 흰박스로 가림 (빠른 경로, bytes 반환)
    - 사진 컨텐츠(모델/배경) → rembg 전체 배경 제거 (느린 경로)
      → rembg 1·2차 모두 실패하면 None 반환 (원본 그대로 업로드 + AI 배지 부착 방지)
    """
    src = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    # 다운스케일 768px — alpha matting 메모리 폭발 회피 (1024px도 numpy 단편화로 1.86GiB 단일 할당 실패)
    if max(src.size) > 768:
        ratio = 768 / max(src.size)
        src = src.resize(
            (int(src.width * ratio), int(src.height * ratio)), Image.LANCZOS
        )

    w, h = src.size
    box_w = int(w * _WM_BOX_W_RATIO)
    box_h = int(h * _WM_BOX_H_RATIO)
    box = (w - box_w, 0, w, box_h)
    crop = src.crop(box)

    # 1) 우상단이 거의 순백 → 워터마크 없음, skip
    avg = ImageStat.Stat(crop).mean
    if all(c >= _WM_NO_LOGO_THRESHOLD for c in avg[:3]):
        buf = io.BytesIO()
        src.save(buf, format="WEBP", quality=90)
        return buf.getvalue()

    # 2) 흰배경 + 로고 패턴 → PIL 흰박스 (빠른 경로)
    if _is_white_background_logo(crop):
        ImageDraw.Draw(src).rectangle(box, fill="white")
        buf = io.BytesIO()
        src.save(buf, format="WEBP", quality=90)
        return buf.getvalue()

    # 3) 사진 컨텐츠 → rembg 전체 배경 제거
    #    1차: alpha_matting=False (안정적/메모리 적음) → 대부분 케이스에서 충분
    #    가장자리 품질 부족 시 2차: alpha_matting=True (고품질, 메모리 무거움)
    try:
        result = _rembg_full(src, use_alpha_matting=False)
        if _is_bg_removed(result):
            return result
        print(
            "[Worker]   [rembg] 1차(alpha_matting=False) 가장자리 비흰색 → matting on 재시도"
        )
        try:
            result2 = _rembg_full(src, use_alpha_matting=True)
            if _is_bg_removed(result2):
                return result2
        except (MemoryError, np.linalg.LinAlgError) as me:  # type: ignore[name-defined]
            print(f"[Worker]   [rembg] 2차 메모리 폭발 — 1차 결과로 폴백: {me}")
            return result
        except Exception as e:
            print(f"[Worker]   [rembg] 2차 예외 — 1차 결과 사용: {e}")
            return result
        print("[Worker]   [rembg] 2차도 가장자리 품질 부족 — 변환 실패 처리")
        return None
    except Exception as e:
        print(f"[Worker]   [rembg] 1차 예외, 변환 실패 처리: {e}")
        return None


# ── Process one image URL ─────────────────────────────────
async def process_image(client: httpx.AsyncClient, url: str) -> str | None:
    """이미지 다운로드 → 배경제거 → R2 업로드.

    다운로드는 3회 재시도(1.5s/3s 백오프) — 일시적 네트워크/소싱처 장애 회복.
    """
    resp = None
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            resp = await client.get(url, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            break
        except Exception as e:
            last_err = e
            resp = None
            if attempt < 2:
                await asyncio.sleep(1.5 * (attempt + 1))
    if resp is None:
        print(f"[Worker]   [download] 3회 실패 ({url[:60]}): {last_err}")
        return None

    try:
        processed = await asyncio.to_thread(remove_watermark, resp.content)
        if processed is None:
            # rembg 폴백 실패 — 원본 유지, 변환된 것으로 카운트하지 않음
            return None
        md5 = hashlib.md5(resp.content).hexdigest()[:8]
        filename = f"ai_{md5}_{uuid.uuid4().hex[:6]}.webp"
        result_url = upload_to_r2(processed, filename)
        return result_url
    except Exception as e:
        print(f"[Worker]   [process] 처리 실패 ({url[:60]}): {e}")
        return None


# ── Process one job ──────────────────────────────────────
async def process_job(job: dict) -> None:
    job_id = job["job_id"]
    if job_id in SKIP_JOB_IDS:
        print(f"\n[Worker] ⏭ SKIP job (BG_SKIP_JOB_IDS): {job_id}")
        return
    scope: dict = job.get(
        "scope", {"thumbnail": True, "additional": False, "detail": False}
    )
    products: list[dict] = job.get("products", [])
    print(f"\n[Worker] Job start: {job_id} ({len(products)} products)")

    results = []
    cancelled = False
    async with httpx.AsyncClient(
        timeout=30,
        limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
    ) as client:

        async def _is_cancelled() -> bool:
            """잡 상태 조회 — cancelled면 즉시 중단."""
            try:
                r = await client.get(
                    f"{SAMBA_API_URL}/api/v1/samba/proxy/bg-jobs/{job_id}/status",
                    timeout=5,
                )
                if r.status_code == 200:
                    return r.json().get("status") == "cancelled"
            except Exception:
                pass
            return False

        for i, prod in enumerate(products, 1):
            # 매 상품 시작 전 취소 신호 확인
            if await _is_cancelled():
                print(f"[Worker]   ✋ 잡 취소 감지 — {i - 1}/{len(products)}에서 중단")
                cancelled = True
                break
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

            async def _report_progress(
                bump_product: bool = False,
                product_result: dict | None = None,
            ) -> None:
                """사진 단위 진행률 즉시 보고 (실패 무시).

                product_result 전달 시 상품 1건의 결과를 즉시 DB에 반영하도록 요청.
                """
                try:
                    payload = {
                        "image_current": img_done,
                        "image_total": img_total,
                        "current_product_id": pid,
                        "bump_product": bump_product,
                    }
                    if product_result is not None:
                        payload["product_result"] = product_result
                    await client.patch(
                        f"{SAMBA_API_URL}/api/v1/samba/proxy/bg-jobs/{job_id}/progress",
                        headers=HEADERS,
                        json=payload,
                    )
                except Exception:
                    pass

            # 새 상품 시작 즉시 image_total 보고 — 프론트 fallback("0/2"=상품 진행) 방지
            if img_total > 0:
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

            product_result = {
                "product_id": pid,
                "success": transformed > 0,
                "new_images": new_images,
                "new_detail_images": new_detail,
                "transformed_count": transformed,
            }
            results.append(product_result)
            print(
                f"[Worker]   [{i}/{len(products)}] {pid} -> {transformed} images done"
            )
            # 상품 1건 완료 — current 증가 + 결과 즉시 DB 반영
            await _report_progress(bump_product=True, product_result=product_result)

    if cancelled:
        # 취소된 잡: 부분 결과까지만 반영 후 종료 (백엔드 status는 이미 cancelled)
        if results:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    await client.post(
                        f"{SAMBA_API_URL}/api/v1/samba/proxy/bg-jobs/{job_id}/complete",
                        headers=HEADERS,
                        json={"results": results, "cancelled": True},
                    )
            except Exception as e:
                print(f"[Worker] cancelled job report 실패(무시): {e}")
        print(f"[Worker] Job cancelled: {len(results)}/{len(products)} 처리됨")
        return

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

    # 부팅 시 stuck running 잡 자동 정리 (이전 워커가 비정상 종료된 경우)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{SAMBA_API_URL}/api/v1/samba/proxy/bg-jobs/worker-reset-running",
                headers=HEADERS,
            )
            if r.status_code == 200:
                rj = r.json()
                cnt = rj.get("reset_count", 0)
                if cnt > 0:
                    print(f"[Worker] 부팅 stuck 잡 정리: {cnt}건 cancelled")
                else:
                    print("[Worker] stuck running 잡 없음")
    except Exception as e:
        print(f"[Worker] reset-running 실패(무시): {e}")

    while True:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # 헬스체크 — 모달이 30초 임계로 워커 alive 판단
                try:
                    await client.patch(
                        f"{SAMBA_API_URL}/api/v1/samba/proxy/bg-jobs/heartbeat",
                        headers=HEADERS,
                        timeout=5,
                    )
                except Exception:
                    pass

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
