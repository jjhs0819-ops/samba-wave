"""R2 transformed/*.webp → transformed/*.jpg 일괄 변환 워커.

배경:
    11번가/스마트스토어/롯데ON 등 마켓 API가 WebP를 거부 → "기본이미지 없음" 에러.
    배경제거 워커가 WebP로 저장한 자산을 JPEG로 변환하여 마켓 등록 가능하도록 한다.

동작:
    1) samba_settings 에서 cloudflare_r2 자격증명 로드
    2) R2 bucket 의 transformed/ai_*.webp 파일 목록 paginated 조회
    3) 각 webp 다운로드 → Pillow 로 JPEG 변환 → 같은 prefix 에 .jpg 업로드
    4) 원본 webp 는 유지 (롤백 안전)
    5) HeadObject 로 이미 jpg 가 있으면 스킵

실행:
    로컬 PC 또는 VM 컨테이너 에서 단독 실행.
    여러 번 실행해도 안전(idempotent — 이미 변환된 파일은 skip).
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time
from typing import Any

import asyncpg
from PIL import Image

from backend.core.config import settings

logger = logging.getLogger("convert_webp_to_jpg")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)


async def _load_r2_creds() -> dict[str, str]:
    """samba_settings 테이블에서 cloudflare_r2 자격증명 조회."""
    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        row = await conn.fetchrow(
            "SELECT value FROM samba_settings WHERE key='cloudflare_r2'"
        )
        if not row:
            raise RuntimeError("samba_settings.cloudflare_r2 설정이 비어있습니다.")
        val = row["value"]
        if isinstance(val, str):
            val = json.loads(val)
        return val
    finally:
        await conn.close()


def _make_r2_client(creds: dict[str, str], max_pool_connections: int = 64):
    import boto3
    from botocore.config import Config

    account_id = str(creds.get("accountId", "")).strip()
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=str(creds.get("accessKey", "")).strip(),
        aws_secret_access_key=str(creds.get("secretKey", "")).strip(),
        region_name="auto",
        config=Config(
            max_pool_connections=max_pool_connections,
            retries={"max_attempts": 3, "mode": "adaptive"},
        ),
    )


def _list_webp_keys(client: Any, bucket: str, prefix: str) -> list[str]:
    """prefix 하위 .webp 객체 전체 키를 페이지네이션으로 수집."""
    keys: list[str] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            k = obj.get("Key", "")
            if k.endswith(".webp"):
                keys.append(k)
    return keys


def _convert_one(
    client: Any, bucket: str, src_key: str, dst_key: str, quality: int
) -> tuple[bool, str]:
    """단일 webp → jpg 변환 + 업로드. (성공여부, 메시지) 반환.

    이미 dst_key 존재 시 skip 으로 처리.
    """
    try:
        client.head_object(Bucket=bucket, Key=dst_key)
        return True, "skip(exists)"
    except Exception:
        pass

    try:
        resp = client.get_object(Bucket=bucket, Key=src_key)
        webp_bytes = resp["Body"].read()
    except Exception as e:
        return False, f"download_fail: {e}"

    try:
        with Image.open(io.BytesIO(webp_bytes)) as im:
            im = im.convert("RGB")
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=quality, optimize=True)
            jpg_bytes = buf.getvalue()
    except Exception as e:
        return False, f"convert_fail: {e}"

    try:
        client.put_object(
            Bucket=bucket,
            Key=dst_key,
            Body=jpg_bytes,
            ContentType="image/jpeg",
        )
        return True, "uploaded"
    except Exception as e:
        return False, f"upload_fail: {e}"


async def main(prefixes: list[str], quality: int, max_workers: int):
    creds = await _load_r2_creds()
    bucket = str(creds.get("bucketName", "")).strip()
    if not bucket:
        raise RuntimeError("bucketName 없음")
    client = _make_r2_client(creds, max_pool_connections=max(max_workers * 2, 32))
    logger.info(f"R2 bucket={bucket} prefixes={prefixes}")

    all_keys: list[str] = []
    for p in prefixes:
        ks = _list_webp_keys(client, bucket, p)
        logger.info(f"  prefix={p} webp 개수={len(ks):,}")
        all_keys.extend(ks)
    logger.info(f"전체 변환 대상: {len(all_keys):,}건")

    if not all_keys:
        logger.info("변환 대상 없음 — 종료")
        return

    # 동시 처리 — ThreadPoolExecutor 로 boto3 호출 병렬화
    from concurrent.futures import ThreadPoolExecutor

    loop = asyncio.get_running_loop()
    pool = ThreadPoolExecutor(max_workers=max_workers)
    started = time.monotonic()
    done = 0
    ok = 0
    skip = 0
    fail = 0
    fail_log: list[tuple[str, str]] = []

    async def _process(src_key: str):
        nonlocal done, ok, skip, fail
        dst_key = src_key[:-5] + ".jpg"  # .webp → .jpg
        success, msg = await loop.run_in_executor(
            pool, _convert_one, client, bucket, src_key, dst_key, quality
        )
        done += 1
        if success:
            if msg.startswith("skip"):
                skip += 1
            else:
                ok += 1
        else:
            fail += 1
            fail_log.append((src_key, msg))
        if done % 200 == 0 or done == len(all_keys):
            elapsed = time.monotonic() - started
            rate = done / max(elapsed, 0.001)
            logger.info(
                f"진행 {done:,}/{len(all_keys):,} "
                f"(ok={ok:,} skip={skip:,} fail={fail:,}) "
                f"{rate:.1f}건/초 elapsed={elapsed:.0f}s"
            )

    # asyncio.gather 로 묶되 max_workers 보다 큰 동시 처리는 의미 없으므로 chunk 분할
    BATCH = max_workers * 4
    for i in range(0, len(all_keys), BATCH):
        chunk = all_keys[i : i + BATCH]
        await asyncio.gather(*(_process(k) for k in chunk))

    pool.shutdown(wait=True)
    elapsed = time.monotonic() - started
    logger.info(
        f"완료 — 총 {done:,}건 ok={ok:,} skip={skip:,} fail={fail:,} ({elapsed:.0f}s)"
    )
    if fail_log:
        logger.warning("실패 목록 (최대 50개):")
        for k, m in fail_log[:50]:
            logger.warning(f"  {k} — {m}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prefix",
        action="append",
        default=None,
        help="변환 대상 prefix (반복 지정). 기본: transformed/ai_ + split/",
    )
    parser.add_argument("--quality", type=int, default=92)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()

    prefixes = args.prefix or ["transformed/ai_", "split/"]
    asyncio.run(main(prefixes, args.quality, args.workers))
