"""Claude API 기반 SEO 최적화 블로그 글 생성기."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import anthropic

from backend.core.config import settings

logger = logging.getLogger(__name__)


class AiWriter:
    """Claude API를 활용한 SEO 최적화 블로그 글 자동 생성 클래스."""

    def __init__(self) -> None:
        # anthropic 비동기 클라이언트 초기화
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def generate_post(
        self,
        issue_title: str,
        issue_description: str,
        category: str,
        language: str = "ko",
        product_info: Optional[dict[str, Any]] = None,
        word_count: int = 1500,
    ) -> dict[str, Any]:
        """SEO 최적화 블로그 글을 생성합니다.

        Args:
            issue_title: 이슈/주제 제목
            issue_description: 이슈/주제 상세 설명
            category: 글 카테고리 (예: 패션, 뷰티, 라이프스타일)
            language: 출력 언어 코드 (기본: "ko")
            product_info: 상품 추천 섹션에 사용할 상품 정보 딕셔너리 (선택)
            word_count: 목표 글자수 (기본: 1500자)

        Returns:
            dict: title, content(HTML), tags(list), excerpt(150자), category 포함
        """
        # 상품 추천 섹션 지시문 구성
        product_section_instruction = ""
        if product_info:
            product_section_instruction = f"""
글 하단에 다음 상품을 자연스럽게 추천하는 섹션을 추가하세요.
상품 정보:
{json.dumps(product_info, ensure_ascii=False, indent=2)}

추천 섹션 형식:
<h2>관련 상품 추천</h2>
<p>이 글과 관련된 상품을 소개합니다.</p>
(상품명, 특징, 추천 이유를 2-3문장으로 자연스럽게 작성)
"""

        # 언어 설정
        lang_label = "한국어" if language == "ko" else language

        prompt = f"""당신은 전문 블로거입니다. SEO 최적화된 블로그 글을 작성해주세요.

주제: {issue_title}
설명: {issue_description}
카테고리: {category}
목표 글자수: {word_count}자 이상
출력 언어: {lang_label}

작성 규칙:
1. H2/H3 소제목을 적극 활용하여 구조화된 글 작성
2. 첫 문단에 핵심 키워드를 자연스럽게 포함
3. 자연스럽고 읽기 편한 문체 사용
4. 같은 내용이 중복되지 않도록 각 섹션마다 새로운 분석/정보 제공
5. 글 마지막에 "마치며" 또는 "결론" 섹션 포함
{product_section_instruction}

반드시 아래 JSON 형식으로만 응답하세요 (마크다운 코드블록 없이 순수 JSON):
{{
  "title": "SEO에 최적화된 매력적인 글 제목",
  "content": "HTML 형식의 전체 본문 (<h2>, <h3>, <p>, <ul>, <li> 태그 사용)",
  "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"],
  "excerpt": "글 요약 (150자 이내, 검색 결과에 표시될 설명)",
  "category": "{category}"
}}"""

        try:
            response = await self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )

            raw_text = response.content[0].text.strip()

            # 마크다운 코드블록 제거 후 JSON 파싱
            cleaned = self._strip_markdown_codeblock(raw_text)
            result: dict[str, Any] = json.loads(cleaned)
            return result

        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.warning("AI 글 생성 JSON 파싱 실패, fallback 반환: %s", e)
            return self._fallback_post(issue_title, issue_description, category)
        except anthropic.APIError as e:
            logger.error("Claude API 오류 (generate_post): %s", e)
            return self._fallback_post(issue_title, issue_description, category)
        except Exception as e:
            logger.error("예상치 못한 오류 (generate_post): %s", e)
            return self._fallback_post(issue_title, issue_description, category)

    async def generate_image_prompt(
        self,
        title: str,
        category: str,
    ) -> str:
        """블로그 대표 이미지 생성용 영문 프롬프트를 생성합니다.

        Args:
            title: 블로그 글 제목
            category: 글 카테고리

        Returns:
            str: 이미지 생성 AI에 전달할 영문 프롬프트 (50단어 이내)
        """
        prompt = f"""Generate a concise English image prompt (under 50 words) for a blog post cover image.

Blog title: {title}
Category: {category}

Requirements:
- Photorealistic or clean illustration style
- Professional and visually appealing
- Relevant to the topic
- No text or typography in the image

Respond with only the image prompt, nothing else."""

        try:
            response = await self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )

            image_prompt = response.content[0].text.strip()
            return image_prompt

        except anthropic.APIError as e:
            logger.warning("Claude API 오류 (generate_image_prompt): %s", e)
            return self._default_image_prompt(category)
        except Exception as e:
            logger.warning("이미지 프롬프트 생성 실패, 기본 프롬프트 반환: %s", e)
            return self._default_image_prompt(category)

    # ------------------------------------------------------------------ #
    # 내부 헬퍼 메서드
    # ------------------------------------------------------------------ #

    @staticmethod
    def _strip_markdown_codeblock(text: str) -> str:
        """마크다운 코드블록(```json ... ```) 감싸기를 제거합니다."""
        if text.startswith("```"):
            # 첫 줄(```json 또는 ```) 제거
            lines = text.splitlines()
            # 시작 fence 제거
            start = 1 if lines and lines[0].startswith("```") else 0
            # 끝 fence 제거
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
        """AI 생성 실패 시 기본값을 반환합니다."""
        return {
            "title": issue_title,
            "content": f"<p>{issue_description}</p>",
            "tags": [category],
            "excerpt": issue_description[:150],
            "category": category,
        }

    @staticmethod
    def _default_image_prompt(category: str) -> str:
        """이미지 프롬프트 생성 실패 시 기본 프롬프트를 반환합니다."""
        return (
            f"A clean, professional blog cover image related to {category}, "
            "modern design, soft lighting, high quality photography"
        )
