"""Gemma 4 API 기반 SEO 블로그 포스트 본문 생성."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class AiWriter:
    """Gemma 4 API를 사용해 SEO 블로그 포스트 본문을 생성한다."""

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    async def _call_gemma(self, prompt: str, max_tokens: int = 4000) -> str:
        """Gemma 4 API 호출 래퍼."""
        from backend.domain.samba.ai.gemma_client import generate_text

        return await generate_text(self._api_key, prompt, max_tokens=max_tokens)

    async def generate_post(
        self,
        issue_title: str,
        issue_description: str,
        category: str,
        language: str = "ko",
        product_info: Optional[dict[str, Any]] = None,
        word_count: int = 1500,
    ) -> dict[str, Any]:
        """SEO 블로그 포스트 본문 생성."""
        product_section_instruction = ""
        if product_info:
            product_section_instruction = f"""
본문 중간에 자연스럽게 상품 관련 섹션을 추가해주세요.
상품 정보:
{json.dumps(product_info, ensure_ascii=False, indent=2)}

상품 정보 섹션 예시:
<h2>추천 상품 정보</h2>
<p>이 이슈와 관련된 상품을 자연스럽게 소개해주세요.</p>
(상품명, 특징, 상품 정보 등을 2-3문단 정도 자연스럽게 포함)
"""

        lang_label = "한국어" if language == "ko" else language

        prompt = f"""당신은 전문 SEO 블로그 작가입니다. SEO 최적화된 블로그 포스트 본문을 작성해주세요.

이슈 제목: {issue_title}
설명: {issue_description}
카테고리: {category}
목표 글자수: {word_count}자 이상
작성 언어: {lang_label}

작성 지침:
1. H2/H3 제목을 포함한 읽기 쉬운 구조의 블로그 본문 작성
2. 너무 기계적이지 않고 자연스러운 문체 사용
3. 독자에게 실제로 도움이 되는 내용 중심
4. 가능하면 관련 사례, 배경 설명, 전망 등을 포함
5. 본문 마지막에는 "핵심 정리" 또는 "마무리" 섹션 포함
{product_section_instruction}

반드시 아래 JSON 형식으로만 응답해주세요(마크다운 코드블록 없이 순수 JSON):
{{
  "title": "SEO에 최적화된 블로그 제목",
  "content": "HTML 형식의 본문 (<h2>, <h3>, <p>, <ul>, <li> 사용 가능)",
  "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"],
  "excerpt": "본문 요약 (150자 내외, 검색 결과용 메타 설명)",
  "category": "{category}"
}}"""

        try:
            raw_text = await self._call_gemma(prompt, max_tokens=4000)
            cleaned = self._strip_markdown_codeblock(raw_text.strip())
            result: dict[str, Any] = json.loads(cleaned)
            return result
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.warning(
                "AI 본문 생성 JSON 파싱 실패, fallback 사용: %s",
                e,
            )
            return self._fallback_post(issue_title, issue_description, category)
        except Exception as e:
            logger.error("Gemma API 오류 (generate_post): %s", e)
            return self._fallback_post(issue_title, issue_description, category)

    @staticmethod
    def _strip_markdown_codeblock(text: str) -> str:
        """마크다운 코드블록 감싸기가 있으면 제거한다."""
        if text.startswith("```"):
            lines = text.splitlines()
            start = 1 if lines and lines[0].startswith("```") else 0
            end = len(lines)
            if lines and lines[-1].strip() == "```":
                end = len(lines) - 1
            text = "\n".join(lines[start:end])
        return text.strip()

    @staticmethod
    def _fallback_post(
        issue_title: str,
        issue_description: str,
        category: str,
    ) -> dict[str, Any]:
        """AI 생성 실패 시 기본 응답."""
        return {
            "title": issue_title,
            "content": f"<p>{issue_description}</p>",
            "tags": [category],
            "excerpt": issue_description[:150],
            "category": category,
        }
