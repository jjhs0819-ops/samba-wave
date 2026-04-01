"""Ken Burns 효과 영상 생성 — 상품 이미지를 줌인/줌아웃+패닝으로 2~3초 영상 변환."""

from __future__ import annotations

import io
import random
import tempfile
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

from backend.utils.logger import logger

# 출력 영상 스펙 — 9:16 세로 (릴스/숏폼 호환)
OUTPUT_WIDTH = 720
OUTPUT_HEIGHT = 1280
FPS = 30
MAX_FILE_SIZE_MB = 2


def _resolve_url(url: str) -> str:
    """프록시 URL에서 실제 이미지 URL 추출."""
    from urllib.parse import urlparse, parse_qs

    if "image-proxy" in url and "url=" in url:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "url" in qs:
            return qs["url"][0]
    return url


def _download_image(url: str) -> Image.Image:
    """URL에서 이미지 다운로드 후 PIL Image 반환."""
    url = _resolve_url(url)
    headers = {"User-Agent": "Mozilla/5.0"}
    if "msscdn.net" in url:
        headers["Referer"] = "https://www.musinsa.com/"
    if "kream-phinf" in url or "pstatic.net" in url:
        headers["Referer"] = "https://kream.co.kr/"
    resp = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGB")


def _resize_cover(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """이미지를 target 크기에 맞게 크롭+리사이즈 (비율 유지, 중앙 크롭)."""
    iw, ih = img.size
    scale = max(target_w / iw, target_h / ih)
    new_w = int(iw * scale)
    new_h = int(ih * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    # 중앙 크롭
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


class KenBurnsEffect:
    """단일 이미지에 Ken Burns 줌/패닝 효과 적용."""

    def __init__(
        self,
        img: Image.Image,
        duration: float = 3.0,
        zoom_start: float = 1.0,
        zoom_end: float = 1.15,
        pan_x: float = 0.0,
        pan_y: float = 0.0,
    ):
        # 줌을 위해 원본보다 크게 준비 (1.3배)
        oversample = 1.3
        self.base_w = int(OUTPUT_WIDTH * oversample)
        self.base_h = int(OUTPUT_HEIGHT * oversample)
        self.base = _resize_cover(img, self.base_w, self.base_h)
        self.base_arr = np.array(self.base)

        self.duration = duration
        self.zoom_start = zoom_start
        self.zoom_end = zoom_end
        self.pan_x = pan_x  # -1.0 ~ 1.0 (좌→우)
        self.pan_y = pan_y  # -1.0 ~ 1.0 (상→하)

    def get_frame(self, t: float) -> np.ndarray:
        """시간 t (초)에 해당하는 프레임 반환."""
        progress = t / self.duration if self.duration > 0 else 0
        progress = min(max(progress, 0), 1)

        # 줌 보간
        zoom = self.zoom_start + (self.zoom_end - self.zoom_start) * progress

        # 줌 적용: 크롭 영역 계산
        crop_w = int(OUTPUT_WIDTH / zoom)
        crop_h = int(OUTPUT_HEIGHT / zoom)

        # 패닝: 중앙에서 pan 방향으로 이동
        max_dx = (self.base_w - crop_w) // 2
        max_dy = (self.base_h - crop_h) // 2

        cx = self.base_w // 2 + int(self.pan_x * max_dx * progress)
        cy = self.base_h // 2 + int(self.pan_y * max_dy * progress)

        x1 = max(0, cx - crop_w // 2)
        y1 = max(0, cy - crop_h // 2)
        x2 = min(self.base_w, x1 + crop_w)
        y2 = min(self.base_h, y1 + crop_h)

        # 경계 보정
        if x2 - x1 < crop_w:
            x1 = max(0, x2 - crop_w)
        if y2 - y1 < crop_h:
            y1 = max(0, y2 - crop_h)

        cropped = self.base_arr[y1:y2, x1:x2]

        # 출력 크기로 리사이즈
        pil_crop = Image.fromarray(cropped)
        pil_resized = pil_crop.resize((OUTPUT_WIDTH, OUTPUT_HEIGHT), Image.LANCZOS)
        return np.array(pil_resized)


def _random_effect_params() -> dict[str, float]:
    """랜덤 Ken Burns 효과 파라미터 생성."""
    effects = [
        {
            "zoom_start": 1.0,
            "zoom_end": 1.15,
            "pan_x": 0.3,
            "pan_y": 0.1,
        },  # 줌인 + 우측
        {
            "zoom_start": 1.15,
            "zoom_end": 1.0,
            "pan_x": -0.3,
            "pan_y": -0.1,
        },  # 줌아웃 + 좌측
        {
            "zoom_start": 1.0,
            "zoom_end": 1.12,
            "pan_x": 0.0,
            "pan_y": 0.3,
        },  # 줌인 + 아래
        {
            "zoom_start": 1.1,
            "zoom_end": 1.0,
            "pan_x": 0.2,
            "pan_y": -0.2,
        },  # 줌아웃 + 우상단
        {
            "zoom_start": 1.0,
            "zoom_end": 1.18,
            "pan_x": -0.2,
            "pan_y": 0.15,
        },  # 줌인 + 좌하단
    ]
    return random.choice(effects)


def generate_kenburns_video(
    image_urls: list[str],
    duration_per_image: float = 1.0,
    max_images: int = 3,
    output_path: str | None = None,
) -> str:
    """상품 이미지로 Ken Burns 효과 영상 생성.

    Args:
      image_urls: 상품 이미지 URL 리스트
      duration_per_image: 이미지당 재생 시간 (초)
      max_images: 사용할 최대 이미지 수
      output_path: 저장 경로 (None이면 임시파일)

    Returns:
      생성된 영상 파일 경로
    """
    from moviepy import VideoClip, concatenate_videoclips

    urls = image_urls[:max_images]
    if not urls:
        raise ValueError("이미지 URL이 없습니다.")

    logger.info(f"[영상생성] Ken Burns 효과 — {len(urls)}장, {duration_per_image}초/장")

    clips: list[VideoClip] = []
    for i, url in enumerate(urls):
        try:
            img = _download_image(url)
            params = _random_effect_params()
            effect = KenBurnsEffect(img, duration=duration_per_image, **params)

            clip = VideoClip(effect.get_frame, duration=duration_per_image)
            clips.append(clip)
            logger.info(f"[영상생성] 이미지 {i + 1}/{len(urls)} 처리 완료")
        except Exception as e:
            logger.warning(f"[영상생성] 이미지 {i + 1} 실패: {e}")
            continue

    if not clips:
        raise ValueError("처리 가능한 이미지가 없습니다.")

    # 클립 연결
    if len(clips) == 1:
        final = clips[0]
    else:
        final = concatenate_videoclips(clips)

    # 출력 경로
    if not output_path:
        tmp = tempfile.NamedTemporaryFile(suffix=".mov", delete=False)
        output_path = tmp.name
        tmp.close()

    # 2MB 이내 목표 — 비트레이트 계산
    target_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
    target_bitrate = int(target_bytes * 8 / final.duration * 0.9)  # 90% 마진
    target_bitrate = min(target_bitrate, 4_000_000)  # 최대 4Mbps

    final.write_videofile(
        output_path,
        fps=FPS,
        codec="libx264",
        audio=False,
        bitrate=f"{target_bitrate}",
        logger=None,
    )

    # 용량 확인
    file_size = Path(output_path).stat().st_size
    logger.info(
        f"[영상생성] 완료 — {output_path} ({final.duration:.1f}초, {file_size / 1024 / 1024:.1f}MB)"
    )
    return output_path
