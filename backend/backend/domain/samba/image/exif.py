"""이미지 EXIF 메타데이터 제거 유틸리티."""

from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)


def strip_exif(image_bytes: bytes) -> bytes:
  """이미지에서 EXIF 메타데이터를 제거하고 깨끗한 바이트를 반환.

  JPEG, PNG, WebP 모두 지원. 실패 시 원본 반환.
  """
  try:
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes))

    # EXIF 제거: 새 이미지로 복사
    clean = Image.new(img.mode, img.size)
    clean.putdata(list(img.getdata()))

    buf = io.BytesIO()
    fmt = img.format or "JPEG"
    if fmt.upper() == "WEBP":
      clean.save(buf, format="WEBP", quality=95)
    elif fmt.upper() == "PNG":
      clean.save(buf, format="PNG")
    else:
      # JPEG 계열
      if clean.mode in ("RGBA", "P"):
        clean = clean.convert("RGB")
      clean.save(buf, format="JPEG", quality=95)

    return buf.getvalue()
  except Exception as e:
    logger.warning(f"[EXIF] 메타데이터 제거 실패, 원본 반환: {e}")
    return image_bytes
