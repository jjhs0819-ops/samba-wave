"""Hermes (로컬 Ollama) 공통 클라이언트 — 맥미니 Hermes 두뇌 호출.

gemma_client 와 같은 텍스트 생성 인터페이스(generate_text / extract_json)를 제공해,
클라우드 Gemma 대신 로컬 Hermes 로 텍스트 작업을 돌릴 수 있게 한다.

- 비전(이미지 분류)은 미지원 — Hermes3 는 텍스트 전용이므로 해당 작업은 Gemma 유지.
- 접속 주소는 settings.ollama_base_url (기본 http://127.0.0.1:11434).
  같은 머신에서 돌리면 기본값, Tailscale 등으로 원격 맥미니에 붙일 땐
  OLLAMA_BASE_URL=http://<tailscale-ip>:11434 로 지정.
- 인증 없음(로컬 모델) — gemma 와 달리 api_key 인자가 필요 없다.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

# extract_json 은 Gemma 와 동일 로직 재사용 (코드블록 감싸기 허용).
# gemma_client 는 settings 를 import-time 에 읽지 않으므로 top-level import 안전.
from backend.domain.samba.ai.gemma_client import extract_json

logger = logging.getLogger(__name__)

_FALLBACK_BASE_URL = "http://127.0.0.1:11434"
_FALLBACK_MODEL = "hermes3:8b"


def _settings() -> Any:
    # 지연 import — 모듈 import 시점에 BackendSettings(env 필수 필드) 로딩을 강제하지 않는다.
    from backend.core.config import settings

    return settings


def _base_url(override: str | None = None) -> str:
    if override:
        return override.rstrip("/")
    try:
        configured = (_settings().ollama_base_url or "").strip()
    except Exception:  # pragma: no cover - settings 미가용 환경 방어
        configured = ""
    return (configured or _FALLBACK_BASE_URL).rstrip("/")


def _default_model(model: str | None = None) -> str:
    if model:
        return model
    try:
        configured = (_settings().hermes_model or "").strip()
    except Exception:  # pragma: no cover - settings 미가용 환경 방어
        configured = ""
    return configured or _FALLBACK_MODEL


async def generate_text(
    prompt: str,
    *,
    model: str | None = None,
    max_tokens: int = 1024,
    temperature: float | None = None,
    base_url: str | None = None,
    timeout: float = 120.0,
) -> str:
    """Hermes 텍스트 생성 — Ollama /api/generate 호출 (비전 없음).

    gemma_client.generate_text 와 호환되는 반환(생성된 텍스트 문자열).
    네트워크 오류 시 지수 백오프로 최대 3회 재시도한다.
    """
    options: dict[str, Any] = {"num_predict": max_tokens}
    if temperature is not None:
        options["temperature"] = temperature

    body: dict[str, Any] = {
        "model": _default_model(model),
        "prompt": prompt,
        "stream": False,
        "options": options,
    }
    url = f"{_base_url(base_url)}/api/generate"

    last_exc: Exception | None = None
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(3):
            try:
                resp = await client.post(url, json=body)
                resp.raise_for_status()
                data = resp.json()
                return str(data.get("response", ""))
            except (httpx.HTTPError, ValueError) as e:
                last_exc = e
                if attempt < 2:
                    wait = 2 * (attempt + 1)
                    logger.warning("[Hermes] 호출 실패(%s) — %s초 후 재시도", e, wait)
                    await asyncio.sleep(wait)
                    continue
    raise RuntimeError(f"Hermes(Ollama) 호출 실패: {last_exc}")


async def ping(base_url: str | None = None, timeout: float = 5.0) -> bool:
    """Ollama 서버가 응답하는지 헬스 체크 (연결 진단용)."""
    url = f"{_base_url(base_url)}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            return resp.status_code == 200
    except httpx.HTTPError:
        return False


__all__ = ["generate_text", "extract_json", "ping"]
