"""상품 이미지 자동 필터링 — Claude Vision / CLIP 분류.

수집된 상품 이미지에서 순수 이미지컷(단색 배경 + 상품만)만 남기고
모델컷/연출컷/배너/사이즈표 등을 자동 제거한다.

method="claude": Claude Vision API (유료, 고정확도)
method="clip":   CLIP zero-shot 분류 (무료, 로컬)
"""

from __future__ import annotations

import base64
import json
import logging
from io import BytesIO
from typing import Any

import httpx
from PIL import Image
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

# ── CLIP zero-shot 분류 라벨 ──
CLIP_PRODUCT_LABELS = [
    "a product photo on a plain white or solid color background, no person visible",
    "a close-up detail shot of a product without any human body",
    "a product laid flat on a surface, flat lay photography",
    "a product displayed on a hanger or mannequin without real human",
    "shoes photographed from multiple angles on plain background",
    "a sole or bottom view of shoes on plain background",
]
CLIP_OTHER_LABELS = [
    "a person wearing or modeling clothes or shoes",
    "human body parts visible such as feet legs hands arms or torso",
    "a lifestyle or outdoor photoshoot with a person",
    "a text banner, promotional graphic, or advertisement image",
    "a size chart, specification table, or measurement guide",
    "a brand logo or decorative graphic design",
]

# CLIP 모델 싱글턴 캐시 (프로세스당 1회 로드)
_clip_model_cache: dict[str, Any] = {}


def _get_clip_model() -> tuple[Any, Any, Any]:
    """CLIP 모델+전처리기+토크나이저 반환 (최초 1회 로드)."""
    if "model" not in _clip_model_cache:
        import open_clip
        import torch

        model, _, preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained="laion2b_s34b_b79k"
        )
        tokenizer = open_clip.get_tokenizer("ViT-B-32")
        model.eval()

        # 라벨 텍스트 임베딩 사전 계산
        all_labels = CLIP_PRODUCT_LABELS + CLIP_OTHER_LABELS
        text_tokens = tokenizer(all_labels)
        with torch.no_grad():
            text_features = model.encode_text(text_tokens)
            text_features /= text_features.norm(dim=-1, keepdim=True)

        _clip_model_cache["model"] = model
        _clip_model_cache["preprocess"] = preprocess
        _clip_model_cache["text_features"] = text_features
        _clip_model_cache["n_product"] = len(CLIP_PRODUCT_LABELS)

    return (
        _clip_model_cache["model"],
        _clip_model_cache["preprocess"],
        _clip_model_cache["text_features"],
    )


class ImageFilterService:
    """Claude Vision 또는 CLIP으로 이미지 분류 후 필터링."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # 이미지 다운로드 + 인코딩
    # ------------------------------------------------------------------

    async def _download_and_encode(
        self,
        url: str,
        client: httpx.AsyncClient | None = None,
    ) -> tuple[str, str, int, int]:
        """이미지 URL -> 바이트 다운로드 -> 5MB 초과 시 리사이즈 -> base64 인코딩.

        Returns:
          (base64_data, media_type, width, height) 튜플
        """
        _headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": url,
        }

        # 외부에서 클라이언트를 주입받으면 재사용, 없으면 새로 생성
        async def _do_download(c: httpx.AsyncClient) -> tuple[str, str, int, int]:
            # 10MB 초과 이미지는 스킵 (HEAD 실패 시 무시하고 GET 진행)
            try:
                head_resp = await c.head(url, headers=_headers)
                content_length = int(head_resp.headers.get("content-length", 0))
                if content_length > 10_000_000:
                    raise ValueError(
                        f"이미지 크기 초과: {content_length // 1_000_000}MB"
                    )
            except ValueError:
                raise
            except Exception:
                pass  # HEAD 실패 시 GET으로 진행
            resp = await c.get(url, headers=_headers)
            resp.raise_for_status()
            img_bytes = resp.content
            content_type = resp.headers.get("content-type", "image/jpeg")
            media_type = content_type.split(";")[0].strip()
            if not media_type.startswith("image/"):
                media_type = "image/jpeg"

            # Claude Vision 제한: base64 5MB + 해상도 8000px → 초과 시 리사이즈
            img = Image.open(BytesIO(img_bytes))
            w, h = img.size
            if len(img_bytes) > 3_500_000 or w > 7999 or h > 7999:
                img.thumbnail((1500, 1500), Image.LANCZOS)
                if img.mode == "RGBA":
                    img = img.convert("RGB")
                buf = BytesIO()
                img.save(buf, format="JPEG", quality=85)
                img_bytes = buf.getvalue()
                media_type = "image/jpeg"

            b64 = base64.b64encode(img_bytes).decode("ascii")
            return b64, media_type, w, h

        if client:
            return await _do_download(client)
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
            return await _do_download(c)

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
            from backend.domain.samba.forbidden.repository import (
                SambaSettingsRepository,
            )

            repo = SambaSettingsRepository(self.session)
            row = await repo.find_by_async(key="claude")
            if row and isinstance(row.value, dict):
                api_key = row.value.get("apiKey", "")
        except Exception:
            pass
        if not api_key:
            api_key = settings.anthropic_api_key
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY가 설정되지 않았습니다. 설정 > Claude API에서 키를 입력하세요."
            )

        # 이미지 다운로드 + base64 인코딩 (클라이언트 재사용으로 연결 풀링)
        encoded: list[tuple[int, str, str, str]] = []  # (index, url, b64, media_type)
        failed_indices: dict[int, str] = {}  # 다운로드 실패 (idx -> 에러)

        import asyncio

        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        ) as client:
            for idx, url in enumerate(urls):
                # 다운로드 실패 시 1회 재시도
                for attempt in range(2):
                    try:
                        b64, media_type, w, h = await self._download_and_encode(
                            url, client=client
                        )
                        encoded.append((idx, url, b64, media_type))
                        break  # 성공 시 재시도 루프 탈출
                    except Exception as e:
                        if attempt == 0:
                            await asyncio.sleep(1)  # 1초 대기 후 재시도
                            continue
                        logger.warning(
                            f"[이미지필터] 다운로드 2회 실패 (제거 처리): {url[:80]} — {e}"
                        )
                        failed_indices[idx] = str(e)

        if not encoded:
            # 모든 이미지 다운로드 실패 -> 전부 product로 분류 (원본 유지)
            return [{"url": u, "type": "product"} for u in urls]

        # Claude Vision 요청 (최대 20장씩 묶음)
        results: list[dict[str, str]] = []
        client = anthropic.AsyncAnthropic(api_key=api_key)

        for chunk_start in range(0, len(encoded), 20):
            chunk = encoded[chunk_start : chunk_start + 20]

            # 이미지 content 블록 구성
            content: list[dict[str, Any]] = []
            for _, _, b64, media_type in chunk:
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64,
                        },
                    }
                )
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
                        results.append(
                            {"url": real_url, "type": item.get("type", "product")}
                        )
                # Claude 응답에 누락된 이미지는 product로 처리
                matched_indices = {
                    item.get("index")
                    for item in classifications
                    if isinstance(item.get("index"), int)
                }
                for ci_fill in range(len(chunk)):
                    if ci_fill not in matched_indices:
                        results.append({"url": chunk[ci_fill][1], "type": "product"})

            except Exception as e:
                logger.error(f"[이미지필터] Claude Vision 호출 실패: {e}")
                # 실패 시 해당 청크 전부 product로 분류
                for _, url, _, _ in chunk:
                    results.append({"url": url, "type": "product"})

        # 다운로드 실패 이미지 → other로 제거
        for idx, err in failed_indices.items():
            results.append(
                {"url": urls[idx], "type": "other", "reason": f"download_fail:{err}"}
            )

        # 원본 순서대로 정렬
        url_order = {u: i for i, u in enumerate(urls)}
        results.sort(key=lambda r: url_order.get(r["url"], 999))
        return results

    # ------------------------------------------------------------------
    # CLIP zero-shot 분류 (무료)
    # ------------------------------------------------------------------

    async def classify_images_clip(
        self, urls: list[str], threshold: float = 0.0
    ) -> list[dict[str, Any]]:
        """CLIP zero-shot으로 이미지 분류 (무료, 로컬).

        각 이미지에 대해 product/other 라벨 유사도를 계산하고
        product 최대 점수 - other 최대 점수 > threshold → "product".

        Returns:
          [{"url": "...", "type": "product"/"other",
            "score_product": 0.82, "score_other": 0.45}, ...]
        """
        import asyncio

        import torch

        model, preprocess, text_features = _get_clip_model()
        n_product = _clip_model_cache["n_product"]

        results: list[dict[str, Any]] = []

        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        ) as client:
            for url in urls:
                try:
                    # 이미지 다운로드
                    _headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Accept": "image/*,*/*;q=0.8",
                        "Referer": url,
                    }
                    resp = await client.get(url, headers=_headers)
                    resp.raise_for_status()
                    img = Image.open(BytesIO(resp.content)).convert("RGB")

                    # CLIP 전처리 + 추론 (CPU, 동기 → run_in_executor)
                    def _classify_single(img: Image.Image) -> tuple[float, float]:
                        img_tensor = preprocess(img).unsqueeze(0)
                        with torch.no_grad():
                            img_features = model.encode_image(img_tensor)
                            img_features /= img_features.norm(dim=-1, keepdim=True)
                            similarities = (img_features @ text_features.T).squeeze(0)

                        # product 라벨 최대 점수 vs other 라벨 최대 점수
                        product_score = similarities[:n_product].max().item()
                        other_score = similarities[n_product:].max().item()
                        return product_score, other_score

                    loop = asyncio.get_event_loop()
                    product_score, other_score = await loop.run_in_executor(
                        None, _classify_single, img
                    )

                    img_type = (
                        "product"
                        if (product_score - other_score) > threshold
                        else "other"
                    )
                    results.append(
                        {
                            "url": url,
                            "type": img_type,
                            "score_product": round(product_score, 4),
                            "score_other": round(other_score, 4),
                        }
                    )
                    logger.info(
                        f"[이미지필터-CLIP] {img_type:7s} | "
                        f"product={product_score:.4f} other={other_score:.4f} | {url[:80]}"
                    )
                except Exception as e:
                    logger.warning(
                        f"[이미지필터-CLIP] 실패 (other 처리): {url[:80]} — {e}"
                    )
                    results.append(
                        {
                            "url": url,
                            "type": "other",
                            "score_product": 0,
                            "score_other": 0,
                        }
                    )

        return results

    # ------------------------------------------------------------------
    # 정확도 비교 (Claude vs CLIP)
    # ------------------------------------------------------------------

    async def compare_methods(self, urls: list[str]) -> dict[str, Any]:
        """같은 이미지에 Claude + CLIP 둘 다 돌려서 결과 비교."""
        import asyncio

        claude_task = asyncio.create_task(self.classify_images(urls))
        clip_task = asyncio.create_task(self.classify_images_clip(urls))

        claude_results, clip_results = await asyncio.gather(claude_task, clip_task)

        # URL 기준으로 매칭
        claude_map = {r["url"]: r["type"] for r in claude_results}
        clip_map = {r["url"]: r for r in clip_results}

        comparisons = []
        match_count = 0
        for url in urls:
            claude_type = claude_map.get(url, "unknown")
            clip_data = clip_map.get(url, {})
            clip_type = clip_data.get("type", "unknown")
            matched = claude_type == clip_type
            if matched:
                match_count += 1
            comparisons.append(
                {
                    "url": url[-80:],
                    "claude": claude_type,
                    "clip": clip_type,
                    "clip_score_product": clip_data.get("score_product", 0),
                    "clip_score_other": clip_data.get("score_other", 0),
                    "match": matched,
                }
            )

        return {
            "total": len(urls),
            "match_count": match_count,
            "accuracy": round(match_count / len(urls) * 100, 1) if urls else 0,
            "comparisons": comparisons,
        }

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
        self,
        product_id: str,
        scope: str = "images",
        method: str = "claude",
    ) -> dict[str, Any]:
        """단일 상품 이미지 필터링.

        scope: "images" (대표+추가), "detail_images" (추가만), "detail" (상세페이지), "all" (전체)
        method: "claude" (Claude Vision, 유료) | "clip" (CLIP zero-shot, 무료)

        대표+추가이미지 필터링 규칙:
        - 이미지컷이 있으면 나머지 제거
        - 대표이미지(images[0])가 삭제 대상이면 이미지컷으로 대체
        - 이미지컷이 하나도 없으면 작업하지 않음 (AI 변환용 소스 보존)
        """
        from backend.domain.samba.collector.repository import (
            SambaCollectedProductRepository,
        )

        repo = SambaCollectedProductRepository(self.session)
        product = await repo.get_async(product_id)
        if not product:
            return {"action": "skipped", "reason": "not_found"}

        # method에 따라 분류 함수 선택
        _classify = (
            self.classify_images_clip if method == "clip" else self.classify_images
        )

        update_data: dict[str, Any] = {}
        result_info: dict[str, Any] = {"action": "filtered", "method": method}

        # 대표+추가이미지 필터링 (제거 발생 시 자동 2회차 재검증)
        if scope in ("images", "all"):
            images = product.images or []
            if images:
                classifications = await _classify(images)
                product_cuts = [
                    c["url"] for c in classifications if c["type"] == "product"
                ]
                other_cuts = [c["url"] for c in classifications if c["type"] == "other"]

                # 분류 결과 로그
                logger.info(
                    f"[이미지필터-{method}] 상품 {product_id} images 1차 — "
                    f"총 {len(images)}장: product {len(product_cuts)}장, other {len(other_cuts)}장"
                )
                for c in classifications:
                    logger.info(
                        f"[이미지필터-{method}]   {c['type']:7s} | {c['url'][:100]}"
                    )

                # 1차에서 제거 발생 + 남은 이미지 2장 이상 → 2회차 재검증
                if other_cuts and len(product_cuts) >= 2:
                    logger.info(
                        f"[이미지필터-{method}] 상품 {product_id} images 2차 재검증 시작 ({len(product_cuts)}장)"
                    )
                    re_classifications = await _classify(product_cuts)
                    re_product = [
                        c["url"] for c in re_classifications if c["type"] == "product"
                    ]
                    re_other = [
                        c["url"] for c in re_classifications if c["type"] == "other"
                    ]
                    logger.info(
                        f"[이미지필터-{method}] 상품 {product_id} images 2차 — "
                        f"product {len(re_product)}장, other {len(re_other)}장"
                    )
                    for c in re_classifications:
                        logger.info(
                            f"[이미지필터-{method}] 2차 {c['type']:7s} | {c['url'][:100]}"
                        )
                    # 2차에서 추가 제거된 것이 있고, product가 남아있으면 반영
                    if re_other and re_product:
                        other_cuts.extend(re_other)
                        product_cuts = re_product

                cls_detail = [
                    {"url": c["url"][-60:], "type": c["type"]} for c in classifications
                ]
                if not product_cuts:
                    # 이미지컷 없음 → 작업하지 않음 (AI 변환용 소스 보존)
                    logger.warning(
                        f"[이미지필터] 상품 {product_id} — 이미지컷 0장, 필터링 스킵"
                    )
                    result_info["images"] = {
                        "action": "skipped",
                        "reason": "no_product_cuts",
                        "classifications": cls_detail,
                    }
                else:
                    removed = len(images) - len(product_cuts)
                    update_data["images"] = product_cuts
                    result_info["images"] = {
                        "kept": len(product_cuts),
                        "removed": removed,
                        "classifications": cls_detail,
                    }

        # 추가이미지만 필터링 (대표이미지 유지)
        if scope == "detail_images":
            images = product.images or []
            if len(images) > 1:
                main_image = images[0]
                additional = images[1:]
                classifications = await _classify(additional)
                product_cuts = [
                    c["url"] for c in classifications if c["type"] == "product"
                ]
                other_cuts = [c["url"] for c in classifications if c["type"] == "other"]

                logger.info(
                    f"[이미지필터-{method}] 상품 {product_id} 추가이미지 — "
                    f"총 {len(additional)}장: product {len(product_cuts)}장, other {len(other_cuts)}장"
                )
                for c in classifications:
                    logger.info(
                        f"[이미지필터-{method}]   {c['type']:7s} | {c['url'][:100]}"
                    )

                cls_detail = [
                    {"url": c["url"][-60:], "type": c["type"]} for c in classifications
                ]
                removed = len(additional) - len(product_cuts)
                update_data["images"] = [main_image] + product_cuts
                result_info["images"] = {
                    "kept": len(product_cuts),
                    "removed": removed,
                    "classifications": cls_detail,
                }

        # 상세페이지 이미지 필터링 (제거 발생 시 자동 2회차 재검증)
        if scope in ("detail", "all"):
            detail_images = product.detail_images or []
            if detail_images:
                classifications = await _classify(detail_images)
                product_cuts = [
                    c["url"] for c in classifications if c["type"] == "product"
                ]
                other_cuts = [c["url"] for c in classifications if c["type"] == "other"]

                # 분류 결과 로그
                logger.info(
                    f"[이미지필터-{method}] 상품 {product_id} detail 1차 — "
                    f"총 {len(detail_images)}장: product {len(product_cuts)}장, other {len(other_cuts)}장"
                )
                for c in classifications:
                    logger.info(
                        f"[이미지필터-{method}]   {c['type']:7s} | {c['url'][:100]}"
                    )

                # 1차에서 제거 발생 + 남은 이미지 2장 이상 → 2회차 재검증
                if other_cuts and len(product_cuts) >= 2:
                    logger.info(
                        f"[이미지필터-{method}] 상품 {product_id} detail 2차 재검증 시작 ({len(product_cuts)}장)"
                    )
                    re_classifications = await _classify(product_cuts)
                    re_product = [
                        c["url"] for c in re_classifications if c["type"] == "product"
                    ]
                    re_other = [
                        c["url"] for c in re_classifications if c["type"] == "other"
                    ]
                    logger.info(
                        f"[이미지필터-{method}] 상품 {product_id} detail 2차 — "
                        f"product {len(re_product)}장, other {len(re_other)}장"
                    )
                    for c in re_classifications:
                        logger.info(
                            f"[이미지필터-{method}] 2차 {c['type']:7s} | {c['url'][:100]}"
                        )
                    if re_other and re_product:
                        other_cuts.extend(re_other)
                        product_cuts = re_product

                cls_detail = [
                    {"url": c["url"][-60:], "type": c["type"]} for c in classifications
                ]
                if not product_cuts:
                    logger.warning(
                        f"[이미지필터] 상품 {product_id} detail — 이미지컷 0장, 필터링 스킵"
                    )
                    result_info["detail"] = {
                        "action": "skipped",
                        "reason": "no_product_cuts",
                        "classifications": cls_detail,
                    }
                else:
                    removed = len(detail_images) - len(product_cuts)
                    update_data["detail_images"] = product_cuts
                    result_info["detail"] = {
                        "kept": len(product_cuts),
                        "removed": removed,
                        "classifications": cls_detail,
                    }

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
        self,
        product_ids: list[str],
        scope: str = "images",
        method: str = "claude",
    ) -> dict[str, Any]:
        """다중 상품 일괄 필터링. 상품 단위 커밋 (부분 성공 허용)."""
        results: dict[str, Any] = {}
        errors: dict[str, str] = {}

        for pid in product_ids:
            try:
                result = await self.filter_product(pid, scope=scope, method=method)
                results[pid] = result
            except Exception as e:
                logger.error(f"[이미지필터] 상품 {pid} 처리 실패: {e}")
                errors[pid] = str(e)

        # 제거 합산 집계
        total_removed = 0
        for r in results.values():
            for key in ("images", "detail"):
                info = r.get(key, {})
                if isinstance(info, dict):
                    total_removed += info.get("removed", 0)

        return {
            "success": True,
            "results": results,
            "total": len(results),
            "total_removed": total_removed,
            "errors": errors,
        }

    async def filter_by_group(
        self, filter_id: str, scope: str = "images", method: str = "claude"
    ) -> dict[str, Any]:
        """수집 그룹(search_filter_id) 단위 필터링."""
        from backend.domain.samba.collector.repository import (
            SambaCollectedProductRepository,
        )

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

        return await self.batch_filter(product_ids, scope=scope, method=method)
