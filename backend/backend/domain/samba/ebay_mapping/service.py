"""eBay 매핑 Service — 조회 + Claude 폴백 + 시드."""

from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.samba.ebay_mapping.repository import SambaEbayMappingRepository
from backend.domain.samba.ebay_mapping.seed import get_all_seeds
from backend.utils.logger import logger


class SambaEbayMappingService:
    """eBay 한/영 매핑 서비스.

    조회 흐름:
      1. DB 조회 (manual > ai > default)
      2. 없으면 Claude API 호출
      3. 결과를 DB에 source='ai'로 저장
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SambaEbayMappingRepository(session)

    async def translate(
        self, category: str, kr_value: str, fallback: Optional[str] = None
    ) -> str:
        """한글 값을 영문으로 변환. DB → Claude 순서.

        category: 'color' | 'material' | 'origin' | 'sex' | 'type'
        kr_value: 한글 원본 (예: '검정')
        fallback: DB/Claude 모두 실패 시 반환할 기본값
        """
        if not kr_value or not kr_value.strip():
            return fallback or ""

        kr_value = kr_value.strip()

        # 이미 영문이면 그대로 반환
        if _is_english(kr_value):
            return kr_value

        # 1. DB 조회
        row = await self.repo.find(category, kr_value)
        if row:
            return row.en_value

        # 2. Claude API 폴백
        translated = await self._translate_with_claude(category, kr_value)
        if translated:
            # DB에 저장 (다음 조회부터 즉시)
            try:
                await self.repo.upsert(category, kr_value, translated, source="ai")
                logger.info(
                    "[eBay매핑] Claude 자동 추가: %s.%s → %s",
                    category,
                    kr_value,
                    translated,
                )
            except Exception as e:
                logger.warning("[eBay매핑] 캐시 저장 실패: %s", e)
            return translated

        return fallback or kr_value

    # 의미없는/폴백 한글 값 — Claude 호출 없이 즉시 폴백
    _MEANINGLESS_KR_VALUES = {
        # 참조 표현
        "상세정보참조",
        "상세 정보 참조",
        "상세정보 참조",
        "상세 이미지 참조",
        "상세이미지참조",
        "상세이미지 참조",
        "상세 이미지참조",
        "이미지참조",
        "이미지 참조",
        "상세페이지 참고",
        "상세페이지참고",
        "상세 페이지 참고",
        "상세페이지 참조",
        "상세페이지참조",
        "상세 참고",
        "상세참고",
        "상세 페이지 참조",
        "본문참조",
        "본문 참조",
        "제품 라벨 참조",
        "라벨 참조",
        "라벨참조",
        "없음",
        "기타",
        "상세설명참조",
        "상세설명 참조",
        # 라벨 이름 자체 (수집기 파싱 실패 시 발생)
        "색상",
        "컬러",
        "색깔",
        "소재",
        "재질",
        "제품 소재",
        "제품소재",
        "원단",
        "재료",
        "제조국",
        "원산지",
        "생산지",
        "제조자",
        "제조사",
        "제조사/수입자",
        "제조사(수입자)",
        "제조사(수입자/병행수입)",
        "수입자",
        "수입국",
        "사이즈",
        "크기",
        "치수",
        "브랜드",
        "모델",
        "성별",
        "시즌",
        "세탁방법",
        "세탁 방법",
        "관리법",
        "상품명",
    }

    # 카테고리별 폴백 (Claude 응답이 부적절하거나 의미없는 한글일 때)
    _FALLBACK_BY_CATEGORY = {
        "color": "Multicolor",
        "material": "Mixed Materials",
        "origin": "China",  # 가장 흔한 원산지
        "sex": "Unisex Adults",
        "brand": "Unbranded",
        "type": "Other",
    }

    # 영문 라벨 이름 — Claude가 잘못 번역해서 이걸 반환한 경우 거부
    _INVALID_LABEL_TRANSLATIONS = {
        "color",
        "material",
        "material composition",
        "country of origin",
        "country of manufacture",
        "manufacturer",
        "size",
        "brand",
        "model",
        "department",
        "type",
        "season",
        "pattern",
        "style",
    }

    @staticmethod
    def _is_invalid_translation(text: str) -> bool:
        """Claude 응답이 거부 응답 또는 부적절한 값인지 확인."""
        if not text or len(text) < 2:
            return True
        lower = text.lower().strip()
        # 영문 라벨 이름 자체 거부 (Claude가 라벨 한글을 그대로 영문 라벨로 번역한 경우)
        if lower in SambaEbayMappingService._INVALID_LABEL_TRANSLATIONS:
            return True
        # 거부 패턴
        refusal_patterns = [
            "i cannot",
            "i can't",
            "i'm unable",
            "i am unable",
            "i need to",
            "i should",
            "i want to",
            "i would need",
            "sorry",
            "apologize",
            "no translation",
            "cannot provide",
            "can't provide",
            "not possible",
            "see item details",
            "see details",
            "see description",
            "refer to",
            "please provide",
            "this appears",
            "see product",
            "product details",
            "details reference",
            "n/a",
            "unknown",
            "based on",
            "translation:",
            "english:",
            "note:",
            "clarif",
        ]
        if any(p in lower for p in refusal_patterns):
            return True
        # 한글이 그대로 남아있으면 거부
        if any("가" <= c <= "힣" for c in text):
            return True
        return False

    async def _translate_with_claude(self, category: str, kr_value: str) -> str:
        """Claude API로 한→영 번역. 거부 응답이나 실패 시 폴백 반환."""
        # 의미없는 값은 Claude 호출 없이 즉시 폴백
        if kr_value.strip() in self._MEANINGLESS_KR_VALUES:
            return self._FALLBACK_BY_CATEGORY.get(category, "")

        try:
            import anthropic

            from backend.core.config import settings as app_settings
            from backend.domain.samba.forbidden.model import SambaSettings
            from sqlmodel import select

            # DB에서 Claude API 키 조회
            api_key = ""
            stmt = select(SambaSettings).where(SambaSettings.key == "claude")
            result = await self.session.execute(stmt)
            row = result.scalars().first()
            if row and isinstance(row.value, dict):
                api_key = row.value.get("apiKey", "")
            if not api_key:
                api_key = app_settings.anthropic_api_key
            if not api_key:
                return self._FALLBACK_BY_CATEGORY.get(category, "")

            category_label = {
                "color": "color name",
                "material": "fabric/material name",
                "origin": "country of origin",
                "sex": "target gender/department (Men/Women/Unisex Adults/Kids/Boys/Girls/Baby)",
                "type": "product type category",
                "brand": "brand name",
            }.get(category, category)

            prompt = (
                f"Translate this Korean {category_label} to English for eBay US listing.\n"
                f"Korean: {kr_value}\n\n"
                "Rules:\n"
                "- Use the standard English term commonly used on eBay US\n"
                "- Single value, no explanation\n"
                "- No quotes, no period\n"
                "- Max 30 characters\n"
                "- If the input is meaningless or generic, respond with the most common default value\n"
                "- NEVER refuse or apologize"
            )

            client = anthropic.AsyncAnthropic(api_key=api_key)
            resp = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=50,
                messages=[{"role": "user", "content": prompt}],
            )
            translated = resp.content[0].text.strip().strip('"').strip("'")[:30]

            # Claude 응답 검증 (거부 패턴 등)
            if self._is_invalid_translation(translated):
                logger.warning(
                    "[eBay매핑] Claude 응답 부적절: %s.%s → '%s', 폴백 사용",
                    category,
                    kr_value,
                    translated,
                )
                return self._FALLBACK_BY_CATEGORY.get(category, "")

            return translated
        except Exception as e:
            logger.warning("[eBay매핑] Claude 번역 실패: %s", e)
            return self._FALLBACK_BY_CATEGORY.get(category, "")

    async def seed_defaults(self) -> int:
        """기본 시드 데이터를 DB에 넣는다. 이미 있으면 건너뜀."""
        seeds = get_all_seeds()
        added = 0
        for seed in seeds:
            existing = await self.repo.find(seed["category"], seed["kr_value"])
            if existing:
                continue
            await self.repo.upsert(
                seed["category"],
                seed["kr_value"],
                seed["en_value"],
                source="default",
            )
            added += 1
        logger.info("[eBay매핑] 시드 완료: %d건 추가", added)
        return added


def _is_english(text: str) -> bool:
    """텍스트가 영문+숫자로만 구성되어 있는지 확인."""
    if not text:
        return False
    return all(c.isascii() for c in text)
