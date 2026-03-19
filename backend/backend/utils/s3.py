"""S3 presigned URL 유틸리티."""

import time
from functools import lru_cache

import boto3
from botocore.config import Config as BotoConfig

from backend.core.config import settings


@lru_cache(maxsize=1)
def get_s3_client():
    """boto3 S3 클라이언트 (캐싱)."""
    return boto3.client(
        "s3",
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
        config=BotoConfig(signature_version="s3v4"),
    )


def generate_presigned_put_url(
    s3_key: str,
    content_type: str = "image/png",
    expires_in: int = 300,
) -> str:
    """Presigned PUT URL 생성."""
    client = get_s3_client()
    return client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.s3_bucket_name,
            "Key": s3_key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
    )


def get_public_url(s3_key: str) -> str:
    """S3 공개 URL 생성."""
    return f"https://{settings.s3_bucket_name}.s3.{settings.aws_region}.amazonaws.com/{s3_key}"


def delete_s3_object(s3_key: str) -> None:
    """S3 객체 삭제."""
    client = get_s3_client()
    client.delete_object(Bucket=settings.s3_bucket_name, Key=s3_key)


def build_s3_key(template_id: str, position: str, ext: str) -> str:
    """S3 키 생성. position: top|bottom, ext: png|jpg|webp 등."""
    ts = int(time.time() * 1000)
    return f"samba/detail-templates/{template_id}/{position}_{ts}.{ext}"
