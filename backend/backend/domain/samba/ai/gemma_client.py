"""Gemma 4 API 공통 클라이언트 — Google AI API (generativelanguage) 사용.

텍스트 생성 + 비전(이미지 분류) 모두 지원.
기존 Gemini API 키를 그대로 재사용한다.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# 기본 모델 — MoE 26B (비전 지원, 무료 티어)
DEFAULT_MODEL = "gemma-4-26b-a4b-it"
API_BASE = "https://generativelanguage.googleapis.com/v1beta"


async def _get_gemma_api_key(session: Any) -> str:
    """DB samba_settings에서 Gemini API 키 조회 (Gemma도 동일 키 사용)."""
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository

    repo = SambaSettingsRepository(session)
    row = await repo.find_by_async(key="gemini")
    if row and isinstance(row.value, dict):
        key = str(row.value.get("apiKey", "")).strip()
        if key:
            return key
    raise ValueError("Gemini/Gemma API Key가 설정되지 않았습니다.")


async def generate_text(
    api_key: str,
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 1024,
    temperature: float | None = None,
) -> str:
    """Gemma 4 텍스트 생성 (비전 없음)."""
    gen_config: dict[str, Any] = {"maxOutputTokens": max_tokens}
    if temperature is not None:
        gen_config["temperature"] = temperature

    body: dict[str, Any] = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": gen_config,
    }
    url = f"{API_BASE}/models/{model}:generateContent?key={api_key}"

    async with httpx.AsyncClient(timeout=120) as client:
        for attempt in range(3):
            resp = await client.post(
                url, json=body, headers={"Content-Type": "application/json"}
            )
            if resp.status_code == 429 and attempt < 2:
                wait = 30 * (attempt + 1)
                logger.warning(f"[Gemma] 429 rate limit — {wait}초 대기")
                await asyncio.sleep(wait)
                continue
            break

    if resp.status_code != 200:
        raise RuntimeError(f"Gemma API 오류 {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise ValueError("Gemma 응답에 candidates 없음")
    return candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")


async def classify_image(
    api_key: str,
    image_bytes: bytes,
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 20,
    mime_type: str = "image/jpeg",
) -> str:
    """Gemma 4 비전 — 이미지 1장 분류."""
    img_b64 = base64.b64encode(image_bytes).decode("ascii")
    body: dict[str, Any] = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type, "data": img_b64}},
                ]
            }
        ],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    url = f"{API_BASE}/models/{model}:generateContent?key={api_key}"

    async with httpx.AsyncClient(timeout=60) as client:
        for attempt in range(3):
            resp = await client.post(
                url, json=body, headers={"Content-Type": "application/json"}
            )
            if resp.status_code == 429 and attempt < 2:
                wait = 30 * (attempt + 1)
                logger.warning(f"[Gemma-Vision] 429 rate limit — {wait}초 대기")
                await asyncio.sleep(wait)
                continue
            break

    if resp.status_code != 200:
        raise RuntimeError(
            f"Gemma Vision API 오류 {resp.status_code}: {resp.text[:300]}"
        )

    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise ValueError("Gemma Vision 응답에 candidates 없음")
    return candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")


async def classify_images_batch(
    api_key: str,
    image_bytes_list: list[bytes],
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 20,
) -> list[str]:
    """여러 이미지를 순차 분류."""
    results: list[str] = []
    for img_bytes in image_bytes_list:
        try:
            result = await classify_image(
                api_key, img_bytes, prompt, model=model, max_tokens=max_tokens
            )
            results.append(result)
        except Exception as e:
            logger.warning(f"[Gemma-Vision] 분류 실패: {e}")
            results.append("")
    return results


def extract_json(text: str) -> Any:
    """Gemma 응답에서 JSON 추출 (코드블록 감싸기 허용)."""
    cleaned = text.strip()
    # ```json ... ``` 제거
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        start = 1 if lines[0].startswith("```") else 0
        end = len(lines)
        if lines[-1].strip() == "```":
            end -= 1
        cleaned = "\n".join(lines[start:end]).strip()
    # JSON 배열/객체 시작 위치 찾기
    for i, ch in enumerate(cleaned):
        if ch in ("{", "["):
            # 끝 위치 찾기
            depth = 0
            for j in range(i, len(cleaned)):
                if cleaned[j] in ("{", "["):
                    depth += 1
                elif cleaned[j] in ("}", "]"):
                    depth -= 1
                    if depth == 0:
                        return json.loads(cleaned[i : j + 1])
            break
    return json.loads(cleaned)
