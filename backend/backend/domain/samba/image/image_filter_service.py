"""상품 이미지 자동 필터링 — Claude Vision 분류 + Fireworks 변환.

수집된 상품 이미지에서 순수 이미지컷(단색 배경 + 상품만)만 남기고
모델컷/연출컷/배너/사이즈표 등을 자동 제거한다.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.core.config import settings

logger = logging.getLogger(__name__)

# Claude Vision 분류 프롬프트
CLASSIFY_PROMPT = """아래 상품 이미지들을 각각 분류하세요:

- "product": 사람의 신체가 전혀 보이지 않고, 단색 또는 단순 배경에 상품만 단독 촬영된 사진
  (행거컷, 평놓기, 마네킹, 각도별 촬영, 디테일 클로즈업, 밑창 등)
- "other": 그 외 모든 이미지

"other"로 분류해야 하는 경우 (하나라도 해당하면 other):
- 사람의 신체 일부가 보임 (발, 다리, 팔, 손, 몸통 등 — 배경색 무관)
- 모델이 상품을 착용/신고 있음 (신발 신은 발, 옷 입은 모습 등)
- 연출/라이프스타일 사진 (야외, 실내 인테리어, 소품 등)
- 브랜드 배너, 사이즈표, 스펙표, 로고, 텍스트 이미지

"product"로 분류하는 경우:
- 상품 자체에 사람이 프린팅/인쇄된 경우는 "product"
- 배경이 단색(흰색, 회색, 검정 등)이고 상품만 있고 신체가 없으면 "product"

이미지 순서대로 JSON 배열로만 답변 (다른 텍스트 없이):
[{"index": 0, "type": "product"}, {"index": 1, "type": "other"}, ...]"""


class ImageFilterService:
  """Claude Vision으로 이미지 분류 후 필터링."""

  def __init__(self, session: AsyncSession) -> None:
    self.session = session

  # ------------------------------------------------------------------
  # 이미지 다운로드 + 인코딩
  # ------------------------------------------------------------------

  async def _download_and_encode(self, url: str) -> tuple[str, str]:
    """이미지 URL -> 바이트 다운로드 -> 5MB 초과 시 리사이즈 -> base64 인코딩.

    Returns:
      (base64_data, media_type) 튜플
    """
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
      # 10MB 초과 이미지는 스킵 (메모리 보호)
      head_resp = await client.head(url, headers={"User-Agent": "Mozilla/5.0", "Referer": url})
      content_length = int(head_resp.headers.get("content-length", 0))
      if content_length > 10_000_000:
        raise ValueError(f"이미지 크기 초과: {content_length // 1_000_000}MB")
      resp = await client.get(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": url,
      })
      resp.raise_for_status()
      img_bytes = resp.content
      content_type = resp.headers.get("content-type", "image/jpeg")
      media_type = content_type.split(";")[0].strip()
      if not media_type.startswith("image/"):
        media_type = "image/jpeg"

      # Claude Vision base64 제한 5MB → 원본 3.5MB 이상이면 리사이즈
      if len(img_bytes) > 3_500_000:
        from io import BytesIO
        from PIL import Image
        img = Image.open(BytesIO(img_bytes))
        # 장축 1500px로 축소
        img.thumbnail((1500, 1500), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        img_bytes = buf.getvalue()
        media_type = "image/jpeg"

      b64 = base64.b64encode(img_bytes).decode("ascii")
    return b64, media_type

  # ------------------------------------------------------------------
  # Claude Vision 분류
  # ------------------------------------------------------------------

  async def classify_images(self, urls: list[str]) -> list[dict[str, str]]:
    """이미지 URL 리스트를 Claude Vision으로 분류.

    최대 20장을 1회 요청에 묶어 전송한다.
    다운로드 실패한 이미지는 "product"로 분류 (원본 유지).

    Returns:
      [{"url": "...", "type": "product"/"other"}, ...]
    """
    import anthropic

    # DB settings에서 Claude API Key 조회 → 없으면 env fallback
    api_key = ""
    try:
      from backend.domain.samba.forbidden.repository import SambaSettingsRepository
      repo = SambaSettingsRepository(self.session)
      row = await repo.find_by_async(key="claude")
      if row and isinstance(row.value, dict):
        api_key = row.value.get("apiKey", "")
    except Exception:
      pass
    if not api_key:
      api_key = settings.anthropic_api_key
    if not api_key:
      raise ValueError("ANTHROPIC_API_KEY가 설정되지 않았습니다. 설정 > Claude API에서 키를 입력하세요.")

    # 이미지 다운로드 + base64 인코딩
    encoded: list[tuple[int, str, str, str]] = []  # (index, url, b64, media_type)
    failed_indices: set[int] = set()

    for idx, url in enumerate(urls):
      try:
        b64, media_type = await self._download_and_encode(url)
        encoded.append((idx, url, b64, media_type))
      except Exception as e:
        logger.warning(f"[이미지필터] 다운로드 실패 (원본 유지): {url[:80]} — {e}")
        failed_indices.add(idx)

    if not encoded:
      # 모든 이미지 다운로드 실패 -> 전부 product로 분류 (원본 유지)
      return [{"url": u, "type": "product"} for u in urls]

    # Claude Vision 요청 (최대 20장씩 묶음)
    results: list[dict[str, str]] = []
    client = anthropic.AsyncAnthropic(api_key=api_key)

    for chunk_start in range(0, len(encoded), 20):
      chunk = encoded[chunk_start:chunk_start + 20]

      # 이미지 content 블록 구성
      content: list[dict[str, Any]] = []
      for _, _, b64, media_type in chunk:
        content.append({
          "type": "image",
          "source": {"type": "base64", "media_type": media_type, "data": b64},
        })
      content.append({"type": "text", "text": CLASSIFY_PROMPT})

      try:
        # 429 rate limit 대비 재시도
        for attempt in range(3):
            try:
                response = await client.messages.create(
                  model="claude-sonnet-4-20250514",
                  max_tokens=1024,
                  messages=[{"role": "user", "content": content}],
                )
                break
            except anthropic.RateLimitError:
                if attempt < 2:
                    import asyncio
                    await asyncio.sleep(60 * (attempt + 1))
                else:
                    raise
        # 응답 파싱
        text = response.content[0].text.strip()
        # JSON 배열 추출 (앞뒤 마크다운 코드블록 제거)
        if text.startswith("```"):
          text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        classifications = json.loads(text)

        # Claude의 index 값 기반으로 정확한 매핑
        for item in classifications:
          ci = item.get("index", -1)
          if isinstance(ci, int) and 0 <= ci < len(chunk):
            real_url = chunk[ci][1]
            results.append({"url": real_url, "type": item.get("type", "product")})
        # Claude 응답에 누락된 이미지는 product로 처리
        matched_indices = {item.get("index") for item in classifications if isinstance(item.get("index"), int)}
        for ci_fill in range(len(chunk)):
          if ci_fill not in matched_indices:
            results.append({"url": chunk[ci_fill][1], "type": "product"})

      except Exception as e:
        logger.error(f"[이미지필터] Claude Vision 호출 실패: {e}")
        # 실패 시 해당 청크 전부 product로 분류
        for _, url, _, _ in chunk:
          results.append({"url": url, "type": "product"})

    # 다운로드 실패한 이미지도 product로 추가
    for idx in failed_indices:
      results.append({"url": urls[idx], "type": "product"})

    # 원본 순서대로 정렬
    url_order = {u: i for i, u in enumerate(urls)}
    results.sort(key=lambda r: url_order.get(r["url"], 999))
    return results

  # ------------------------------------------------------------------
  # Fireworks AI 변환 (모델컷/연출컷 -> 이미지컷)
  # ------------------------------------------------------------------

  async def _transform_to_product_cuts(self, urls: list[str]) -> list[str]:
    """모델컷/연출컷을 rembg 배경제거로 변환.

    기존 ImageTransformService의 rembg 메서드를 재사용한다.
    """
    from backend.domain.samba.image.service import ImageTransformService

    svc = ImageTransformService(self.session)

    transformed_urls: list[str] = []
    for url in urls:
      try:
        img_bytes = await svc._download_image(url)
        result_bytes = await svc._remove_background_rembg(img_bytes)
        new_url = await svc._save_image(result_bytes, url)
        transformed_urls.append(new_url)
      except Exception as e:
        logger.error(f"[이미지필터] 이미지 변환 실패: {url[:80]} — {e}")
        transformed_urls.append(url)  # 실패 시 원본 유지
    return transformed_urls

  # ------------------------------------------------------------------
  # 상품 필터링
  # ------------------------------------------------------------------

  async def filter_product(
    self, product_id: str, scope: str = "images",
  ) -> dict[str, Any]:
    """단일 상품 이미지 필터링.

    scope: "images" (대표+추가), "detail" (상세페이지), "all" (전체)

    대표+추가이미지 필터링 규칙:
    - 이미지컷이 있으면 나머지 제거
    - 대표이미지(images[0])가 삭제 대상이면 이미지컷으로 대체
    - 이미지컷이 하나도 없으면 작업하지 않음 (AI 변환용 소스 보존)
    """
    from backend.domain.samba.collector.repository import SambaCollectedProductRepository

    repo = SambaCollectedProductRepository(self.session)
    product = await repo.get_async(product_id)
    if not product:
      return {"action": "skipped", "reason": "not_found"}

    update_data: dict[str, Any] = {}
    result_info: dict[str, Any] = {"action": "filtered"}

    # 대표+추가이미지 필터링
    if scope in ("images", "all"):
      images = product.images or []
      if images:
        classifications = await self.classify_images(images)
        product_cuts = [c["url"] for c in classifications if c["type"] == "product"]

        if not product_cuts:
          # 이미지컷 없음 → 작업하지 않음 (AI 변환용 소스 보존)
          result_info["images"] = {"action": "skipped", "reason": "no_product_cuts"}
        else:
          removed = len(images) - len(product_cuts)
          update_data["images"] = product_cuts
          result_info["images"] = {"kept": len(product_cuts), "removed": removed}

    # 상세페이지 이미지 필터링
    if scope in ("detail", "all"):
      detail_images = product.detail_images or []
      if detail_images:
        classifications = await self.classify_images(detail_images)
        product_cuts = [c["url"] for c in classifications if c["type"] == "product"]

        if not product_cuts:
          result_info["detail"] = {"action": "skipped", "reason": "no_product_cuts"}
        else:
          removed = len(detail_images) - len(product_cuts)
          update_data["detail_images"] = product_cuts
          result_info["detail"] = {"kept": len(product_cuts), "removed": removed}

    if update_data:
      # __img_filtered__ 태그 추가
      existing_tags = product.tags or []
      if "__img_filtered__" not in existing_tags:
        update_data["tags"] = existing_tags + ["__img_filtered__"]
      await repo.update_async(product_id, **update_data)
    else:
      result_info["action"] = "skipped"
      result_info["reason"] = "nothing_to_update"

    return result_info

  async def batch_filter(
    self, product_ids: list[str], scope: str = "images",
  ) -> dict[str, Any]:
    """다중 상품 일괄 필터링. 상품 단위 커밋 (부분 성공 허용)."""
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}

    for pid in product_ids:
      try:
        result = await self.filter_product(pid, scope=scope)
        results[pid] = result
      except Exception as e:
        logger.error(f"[이미지필터] 상품 {pid} 처리 실패: {e}")
        errors[pid] = str(e)

    return {
      "success": True,
      "results": results,
      "total": len(results),
      "errors": errors,
    }

  async def filter_by_group(self, filter_id: str) -> dict[str, Any]:
    """수집 그룹(search_filter_id) 단위 필터링."""
    from backend.domain.samba.collector.repository import SambaCollectedProductRepository

    repo = SambaCollectedProductRepository(self.session)
    products = await repo.list_by_filter(filter_id, skip=0, limit=10000)
    product_ids = [p.id for p in products]

    if not product_ids:
      return {
        "success": True,
        "results": {},
        "total": 0,
        "errors": {},
        "message": "해당 그룹에 상품이 없습니다.",
      }

    return await self.batch_filter(product_ids)
