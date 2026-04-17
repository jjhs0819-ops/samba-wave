"""시딩 + AI 배치 매핑 Mixin."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.samba.category.rules import (
    MARKET_CATEGORIES,
    _detect_gender,
    _expand_synonyms,
    _filter_overseas,
    _filter_to_leaves,
    _rule_match,
    _similarity_match_smartstore,
)

logger = logging.getLogger(__name__)


def _build_fewshot_block(
    batch: List[Dict[str, Any]],
    target_markets: List[str],
) -> str:
    """EXPORTED_RULES에서 같은 소싱사이트+대분류 기준으로 학습 예시를 추출.

    반환값은 프롬프트에 그대로 삽입할 문자열 (비어 있으면 "").
    """
    try:
        from backend.domain.samba.category.rules_exported import EXPORTED_RULES
    except ImportError:
        return ""

    if not EXPORTED_RULES:
        return ""

    examples: list[str] = []
    seen: set[str] = set()

    for item in batch:
        site = item.get("site", "")
        leaf_path = item.get("leaf_path", "")
        if not site or not leaf_path:
            continue
        # 소싱 카테고리 대분류(cat1) 기준으로 유사 예시 추출
        cat1 = leaf_path.split(" > ")[0].strip()

        for market in target_markets:
            exported = EXPORTED_RULES.get((site, market), {})
            count = 0
            for src, tgt in exported.items():
                if not src.startswith(cat1):
                    continue
                # 자기 자신은 제외
                if src == leaf_path:
                    continue
                key = f"{site}|{src}|{market}|{tgt}"
                if key in seen or count >= 3:
                    continue
                seen.add(key)
                examples.append(f"  [{site}] {src} → {market}: {tgt}")
                count += 1
            if len(examples) >= 8:
                break
        if len(examples) >= 8:
            break

    if not examples:
        return ""

    logger.info("[AI매핑] fewshots %d건 주입", len(examples))
    block = "\n[학습 예시 — 아래 패턴과 일관되게 매핑하세요]\n"
    block += "\n".join(examples[:8])
    block += "\n"
    return block


class CategorySeedMixin:
    """시딩 + AI 배치 매핑."""

    # ==================== Market Category Seed ====================

    async def seed_market_categories(self) -> Dict[str, int]:
        """MARKET_CATEGORIES 하드코딩 데이터를 DB SambaCategoryTree에 저장.

        기존 DB 데이터가 있으면 병합 (중복 제거).
        Returns: { market: category_count } 딕셔너리
        """
        result: Dict[str, int] = {}
        for market, cats in MARKET_CATEGORIES.items():
            existing = await self.tree_repo.get_by_site(market)
            if existing:
                db_cats = existing.cat1 or []
                merged = list(dict.fromkeys(db_cats + cats))
                existing.cat1 = merged
                existing.updated_at = datetime.now(UTC)
                self.tree_repo.session.add(existing)
                result[market] = len(merged)
            else:
                await self.tree_repo.create_async(
                    site_name=market,
                    cat1=cats,
                )
                result[market] = len(cats)
        await self.tree_repo.session.commit()
        return result

    async def seed_smartstore_from_api(self, session: "AsyncSession") -> Dict[str, Any]:
        """스마트스토어 실제 카테고리를 API에서 가져와 DB에 저장.

        GET /v1/categories?last=false → wholeCategoryName으로 카테고리 경로 구성.
        """
        from backend.domain.samba.proxy.smartstore import SmartStoreClient
        from backend.domain.samba.forbidden.repository import SambaSettingsRepository
        from backend.domain.samba.account.model import SambaMarketAccount
        from sqlmodel import select

        # 스마트스토어 계정 찾기
        stmt = select(SambaMarketAccount).where(
            SambaMarketAccount.market_type == "smartstore",
            SambaMarketAccount.is_active == True,
        )
        result = await session.execute(stmt)
        account = result.scalars().first()
        if not account:
            return {"error": "활성 스마트스토어 계정이 없습니다"}

        extras = account.additional_fields or {}
        client_id = extras.get("clientId", "") or account.api_key or ""
        client_secret = extras.get("clientSecret", "") or account.api_secret or ""

        if not client_id or not client_secret:
            # Settings 테이블 폴백
            settings_repo = SambaSettingsRepository(session)
            row = await settings_repo.find_by_async(key="smartstore")
            if row and isinstance(row.value, dict):
                client_id = client_id or row.value.get("clientId", "")
                client_secret = client_secret or row.value.get("clientSecret", "")

        if not client_id or not client_secret:
            return {"error": "스마트스토어 API 인증 정보가 없습니다"}

        client = SmartStoreClient(client_id=client_id, client_secret=client_secret)

        # API에서 전체 카테고리 조회
        try:
            api_cats = await client.get_categories(last_only=False)
        except Exception as e:
            return {"error": f"카테고리 API 호출 실패: {e}"}

        if not isinstance(api_cats, list):
            return {"error": "카테고리 API 응답 형식 오류"}

        # wholeCategoryName → 카테고리 경로, id → 코드
        categories: list[str] = []
        code_map: Dict[str, str] = {}
        for cat in api_cats:
            whole_name = cat.get("wholeCategoryName", "")
            cat_id = cat.get("id", "")
            if whole_name:
                # API 형식: "패션잡화>남성신발>스니커즈" → "패션잡화 > 남성신발 > 스니커즈"
                path = " > ".join(p.strip() for p in whole_name.split(">"))
                categories.append(path)
                if cat_id:
                    code_map[path] = str(cat_id)

        if not categories:
            return {"error": "가져온 카테고리가 없습니다"}

        # DB 저장 (기존 데이터 교체)
        existing = await self.tree_repo.get_by_site("smartstore")
        if existing:
            existing.cat1 = categories
            existing.cat2 = code_map
            existing.updated_at = datetime.now(UTC)
            self.tree_repo.session.add(existing)
        else:
            await self.tree_repo.create_async(
                site_name="smartstore",
                cat1=categories,
                cat2=code_map,
            )
        await session.commit()

        logger.info(
            f"[카테고리] 스마트스토어 API에서 {len(categories)}개 카테고리 동기화 완료"
        )
        return {"ok": True, "count": len(categories), "has_codes": bool(code_map)}

    async def seed_market_via_ai(
        self, market_type: str, api_key: str
    ) -> Dict[str, Any]:
        """AI로 마켓의 전체 카테고리 목록을 생성하여 DB에 저장.

        계정/API 없는 마켓도 Claude가 실제 카테고리 체계를 알고 있으므로
        서비스 운영자가 미리 DB를 채워놓을 수 있다.
        """
        import anthropic

        market_label = {
            "smartstore": "네이버 스마트스토어",
            "coupang": "쿠팡",
            "gmarket": "G마켓",
            "auction": "옥션",
            "11st": "11번가",
            "ssg": "SSG(신세계몰)",
            "lotteon": "롯데ON",
            "lottehome": "롯데홈쇼핑",
            "gsshop": "GS샵",
            "homeand": "홈앤쇼핑",
            "hmall": "HMALL(현대홈쇼핑)",
            "kream": "KREAM",
            "ebay": "eBay Korea",
            "lazada": "Lazada",
            "qoo10": "Qoo10",
            "shopee": "Shopee",
        }.get(market_type, market_type)

        prompt = f"""{market_label}의 실제 상품 카테고리 전체 목록을 작성해주세요.

규칙:
1. 실제 {market_label} 셀러센터에서 상품 등록 시 선택하는 카테고리 체계를 따르세요.
2. "대분류 > 중분류 > 소분류 > 세분류" 형태의 전체 경로로 작성하세요.
3. 최하위(리프) 카테고리까지 모두 포함하세요.
4. 주요 카테고리를 빠짐없이 작성하세요 (패션, 뷰티, 식품, 가전, 생활, 스포츠 등).
5. 특히 패션(의류/신발/잡화)과 뷰티(스킨케어/메이크업/헤어/바디) 카테고리는 세분류까지 상세하게 작성하세요.
6. 최소 200개 이상의 리프 카테고리를 포함해주세요.
7. "해외직구", "해외", "해외호텔", "해외여행" 등 해외 관련 카테고리는 절대 포함하지 마세요.
8. JSON 배열만 응답하세요.

예시: ["패션의류 > 여성의류 > 원피스", "뷰티 > 메이크업 > 블러셔", ...]"""

        client = anthropic.AsyncAnthropic(api_key=api_key)
        # 429 rate limit 대비 재시도
        for attempt in range(3):
            try:
                response = await client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=8192,
                    messages=[{"role": "user", "content": prompt}],
                )
                break
            except anthropic.RateLimitError:
                if attempt < 2:
                    logger.warning(
                        "Claude API 429 rate limit — %d초 후 재시도 (%d/3)",
                        60 * (attempt + 1),
                        attempt + 1,
                    )
                    await asyncio.sleep(60 * (attempt + 1))
                else:
                    raise

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3].strip()

        categories = json.loads(text)
        if not isinstance(categories, list) or not categories:
            raise ValueError("AI 응답에서 카테고리 목록을 파싱할 수 없습니다")

        categories = _filter_overseas([str(c) for c in categories if c])

        # DB에 병합 저장
        existing = await self.tree_repo.get_by_site(market_type)
        if existing:
            db_cats = existing.cat1 or []
            merged = list(dict.fromkeys(db_cats + categories))
            existing.cat1 = merged
            existing.updated_at = datetime.now(UTC)
            self.tree_repo.session.add(existing)
            count = len(merged)
        else:
            await self.tree_repo.create_async(site_name=market_type, cat1=categories)
            count = len(categories)
        await self.tree_repo.session.commit()

        logger.info("[AI 시드] %s: %d개 카테고리 생성/병합", market_type, count)
        return {"market": market_type, "count": count, "new": len(categories)}

    async def seed_all_markets_via_ai(self, api_key: str) -> Dict[str, Any]:
        """모든 마켓의 카테고리를 AI로 일괄 생성."""
        markets = list(MARKET_CATEGORIES.keys())
        results: Dict[str, Any] = {}
        for market in markets:
            try:
                result = await self.seed_market_via_ai(market, api_key)
                results[market] = {"ok": True, **result}
            except Exception as e:
                results[market] = {"ok": False, "error": str(e)}
                logger.warning("[AI 시드] %s 실패: %s", market, e)
        return results

    # ==================== Batch AI Category Suggestion ====================

    async def _batch_ai_suggest(
        self,
        items: List[Dict[str, Any]],
        target_markets: List[str],
        api_key: str,
    ) -> List[Any]:
        """여러 카테고리를 배치로 묶어 1회 AI 호출로 처리.

        카테고리 목록을 프롬프트에 넣지 않음 — Claude가 각 마켓의 카테고리 체계를 알고 있으므로
        소싱 카테고리와 상품명만 전달하면 충분. 토큰 대폭 절감.
        10개씩 배치, 배치 간 3초 딜레이.
        """
        import anthropic
        from backend.core.config import settings

        key = api_key or settings.anthropic_api_key
        if not key:
            return ["API 키 없음"] * len(items)

        # 마켓 한글명 매핑 (프롬프트에서 마켓 식별용)
        market_labels: Dict[str, str] = {
            "smartstore": "네이버 스마트스토어",
            "coupang": "쿠팡",
            "gmarket": "G마켓",
            "auction": "옥션",
            "11st": "11번가",
            "ssg": "SSG(신세계몰)",
            "lotteon": "롯데ON",
            "lottehome": "롯데홈쇼핑",
            "gsshop": "GS샵",
        }
        market_names = ", ".join(market_labels.get(m, m) for m in target_markets)

        # DB에서 마켓별 실제 카테고리 목록 조회 (AI가 이 중에서만 선택)
        market_cat_lists: Dict[str, List[str]] = {}
        for m in target_markets:
            try:
                cats = await self._get_market_categories(m)
                if cats:
                    # 모든 마켓 공통: 브랜드/명품/디자이너/해외직구 접두어 카테고리 제외
                    _exclude_prefixes = (
                        "해외직구",
                        "브랜드",
                        "명품",
                        "수입명품",
                        "디자이너",
                        "도서",
                        "음반",
                    )
                    cats = [
                        c
                        for c in cats
                        if not any(c.startswith(p) for p in _exclude_prefixes)
                    ]
                    market_cat_lists[m] = cats
            except Exception:
                pass

        client = anthropic.AsyncAnthropic(api_key=key)
        all_results: List[Any] = []
        # 카테고리 목록 포함 시 배치 크기 축소
        has_cat_list = bool(market_cat_lists)
        batch_size = 5 if has_cat_list else 10

        for batch_start in range(0, len(items), batch_size):
            batch = items[batch_start : batch_start + batch_size]

            cat_entries = []
            for idx, item in enumerate(batch):
                tag_str = ", ".join(item.get("tags", [])[:5])
                seo_str = ", ".join(item.get("seo", [])[:5])
                group_str = ", ".join(item.get("groups", [])[:3])
                sample_names = [n for n in (item.get("samples") or []) if n][:2]
                gender_hint = {
                    "male": "남성",
                    "female": "여성",
                    "unisex": "남녀공용",
                }.get(item.get("gender", ""), "")
                ss_hint = item.get("ss_mapped", "")
                mapped_refs = item.get("mapped_refs", {})
                entry = f"{idx + 1}. [{item['site']}] {item['leaf_path']}"
                if gender_hint:
                    entry += f" | 성별: {gender_hint}"
                if sample_names:
                    entry += f" | 상품명: {' / '.join(sample_names)}"
                # 기존 매핑된 타 마켓 참고 (ss_mapped 포함)
                if mapped_refs:
                    refs_str = ", ".join(
                        f"{mk}:{val}" for mk, val in list(mapped_refs.items())[:4]
                    )
                    entry += f" | 기존매핑참고: {refs_str}"
                elif ss_hint:
                    entry += f" | 스마트스토어매핑: {ss_hint}"
                if seo_str:
                    entry += f" | SEO: {seo_str}"
                if tag_str:
                    entry += f" | 태그: {tag_str}"
                if group_str:
                    entry += f" | 그룹: {group_str}"
                cat_entries.append(entry)

            # 마켓별 카테고리 필터 — leaf 키워드 우선 + 동의어 확장
            cat_list_section = ""
            if has_cat_list:
                import re as _re

                def _split_kw(text: str) -> list[str]:
                    """슬래시/공백/괄호 등으로 분리해 개별 키워드 추출 (2자 이상)."""
                    parts = _re.split(r"[/\s,()·\-]+", text)
                    return [p.strip() for p in parts if len(p.strip()) >= 2]

                # leaf 키워드: 각 아이템의 마지막 세그먼트를 단어 단위로 분리
                leaf_kw: set[str] = set()
                parent_kw: set[str] = set()
                for item in batch:
                    segs = [
                        s.strip() for s in item["leaf_path"].split(">") if s.strip()
                    ]
                    if segs:
                        # 마지막 세그먼트를 통째로 + 단어 분리 모두 추가
                        leaf_kw.add(segs[-1])
                        leaf_kw.update(_split_kw(segs[-1]))
                        for s in segs[:-1]:
                            if len(s) >= 2:
                                parent_kw.add(s)
                                parent_kw.update(_split_kw(s))
                    for t in (item.get("tags") or [])[:3]:
                        if t and len(t) >= 2:
                            leaf_kw.add(t)
                    for kw in (item.get("seo") or [])[:5]:
                        if kw and len(kw) >= 2:
                            leaf_kw.add(kw)
                    for g in (item.get("groups") or [])[:3]:
                        if g and len(g) >= 2:
                            leaf_kw.add(g)
                    # 상품명 키워드 추가 — "기타 하의" 같은 모호한 카테고리 보완
                    for name in (item.get("samples") or [])[:2]:
                        if not name:
                            continue
                        for part in name.replace("/", " ").replace("-", " ").split():
                            if len(part) >= 2:
                                leaf_kw.add(part)

                # 동의어 확장 — 소싱 키워드와 마켓 카테고리 용어 차이 보완
                leaf_kw = _expand_synonyms(leaf_kw)
                parent_kw = _expand_synonyms(parent_kw)

                # 배치 내 소싱 카테고리 원문 (특수 대분류 제외 판별용)
                batch_source_text = " ".join(
                    item["leaf_path"].lower() for item in batch
                )

                # 소싱에 없는 특수 대분류 제외 (2단계와 동일 로직)
                _AI_RESTRICTED_TOPS = [
                    (
                        ["유아동", "유아", "아동", "키즈"],
                        ["유아", "아동", "키즈", "주니어", "베이비"],
                    ),
                    (
                        ["자동차", "모터바이크"],
                        ["자동차", "차량", "모터바이크", "바이크", "오토바이"],
                    ),
                    (
                        ["반려동물", "강아지", "고양이"],
                        ["반려", "강아지", "고양이", "펫"],
                    ),
                    (["수입명품"], ["명품", "럭셔리", "수입명품"]),
                    (["브랜드 "], ["브랜드"]),
                    (
                        ["노트북", "데스크탑", "PC주변"],
                        ["노트북", "데스크탑", "PC", "컴퓨터"],
                    ),
                    (["모니터", "프린터"], ["모니터", "프린터"]),
                    (["저장장치"], ["저장장치", "SSD", "HDD"]),
                    (["영상가전", "계절가전"], ["가전", "TV", "에어컨"]),
                    (["음향기기"], ["스피커", "이어폰", "헤드폰", "음향"]),
                ]

                def _ai_filter_restricted(top_seg: str) -> bool:
                    top_lower = top_seg.lower()
                    for top_kws, require_kws in _AI_RESTRICTED_TOPS:
                        if any(tk in top_lower for tk in top_kws):
                            if not any(rk in batch_source_text for rk in require_kws):
                                return True
                    return False

                lines = []
                has_enough_matches = True
                for m, cats in market_cat_lists.items():
                    # ESM 마켓은 특수 대분류 제외 적용
                    if m in ("gmarket", "auction"):
                        cats = [
                            c
                            for c in cats
                            if not _ai_filter_restricted(c.split(" > ")[0])
                        ]
                    leaf_matches = [c for c in cats if any(kw in c for kw in leaf_kw)]
                    if len(leaf_matches) >= 5:
                        relevant = leaf_matches[:30]
                    else:
                        all_kw = leaf_kw | parent_kw
                        relevant = [c for c in cats if any(kw in c for kw in all_kw)]
                        if len(relevant) < 3:
                            has_enough_matches = False
                        relevant = relevant[:30] if relevant else []
                    if relevant:
                        lines.append(
                            f"- {market_labels.get(m, m)}:\n"
                            + "\n".join(f"  {c}" for c in relevant)
                        )

                if lines and has_enough_matches:
                    cat_list_section = (
                        "\n[허용된 마켓 카테고리 — 이 중에서만 선택]\n"
                        + "\n".join(lines)
                        + "\n"
                    )
                    cat_rule = "각 마켓별로 위 목록에 있는 카테고리 문자열을 정확히 그대로 복사하여 선택. 목록에 없는 카테고리를 임의로 만들거나 변형 금지."
                else:
                    cat_list_section = ""
                    cat_rule = "각 마켓의 허용된 카테고리 중에서만 선택. 존재하지 않는 카테고리 생성 금지."

            # EXPORTED_RULES 기반 학습 예시 구성 (동일 소싱사이트+대분류 패턴)
            fewshot_block = _build_fewshot_block(batch, target_markets)

            prompt = f"""소싱 카테고리를 판매 마켓 카테고리에 매핑.
소비자가 검색할 키워드와 가장 일치하는 카테고리를 선택하세요.
각 항목에 "기존매핑참고"가 있으면 이미 다른 마켓에 매핑된 결과이니 동일 상품 유형으로 매핑하세요.
{fewshot_block}
{chr(10).join(cat_entries)}
{cat_list_section}
규칙:
- {cat_rule}
- 소싱 카테고리의 상품 유형(가방/신발/의류/스포츠 등)을 반드시 유지. 가방→가방, 신발→신발, 의류→의류로만 매핑.
- 성별 매칭 최우선: 항목에 "성별: 남성"이면 남성 카테고리만, "성별: 여성"이면 여성 카테고리만 선택.
- 소싱 카테고리 경로에 "남성", "맨즈", "남자" 단어가 있으면 반드시 남성 카테고리로 매핑.
- 소싱 카테고리 경로에 "여성", "우먼즈", "여자" 단어가 있으면 반드시 여성 카테고리로 매핑.
- 성별 근거가 전혀 없을 때만 남녀공용/성별무관 카테고리 선택 가능.
- 패션 상품(의류/신발/가방/액세서리)은 "패션의류"·"패션잡화" 대분류 우선. "스포츠/레저" 대분류는 소싱 카테고리에 "스포츠", "아웃도어", "골프", "등산", "런닝", "요가", "축구", "농구", "야구", "스키", "자전거" 등 스포츠 키워드가 있을 때만 선택.
- 주니어/아동/유아 카테고리는 절대 선택 금지. KC인증 문제가 있음.
- 도서/음반/교재/학술 카테고리는 절대 선택 금지. 의류학 교재도 포함.
- 의류/패션과 무관한 카테고리(식품, 인테리어, 여행, 자동차, 반려동물 등)는 절대 선택 금지.
- 키워드 단순 매칭 금지. '웨이스트 백'은 허리에 차는 가방이지 바지가 아님. '기타'는 악기가 아닌 기타 등등을 의미함. 상품의 실제 의미를 파악하여 매핑.
- 학습 예시가 있으면 동일 대분류·동일 성별 패턴을 따라 매핑하세요.
- 확신이 없으면 빈 문자열("")로 남길 것. 억지로 맞지 않는 카테고리 선택 금지.
JSON만 응답:
{json.dumps({str(i + 1): {m: "" for m in target_markets} for i in range(len(batch))}, ensure_ascii=False)}"""

            # API 호출 (재시도 포함)
            for attempt in range(3):
                try:
                    response = await client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=2048,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    break
                except anthropic.RateLimitError:
                    if attempt < 2:
                        wait = 60 * (attempt + 1)
                        logger.warning(
                            "[벌크매핑] 429 rate limit — %d초 대기 (배치 %d/%d, 시도 %d/3)",
                            wait,
                            batch_start // batch_size + 1,
                            (len(items) + batch_size - 1) // batch_size,
                            attempt + 1,
                        )
                        await asyncio.sleep(wait)
                    else:
                        for _ in batch:
                            all_results.append("rate limit 초과")
                        continue

            try:
                text = response.content[0].text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                    if text.endswith("```"):
                        text = text[:-3].strip()
                result = json.loads(text)

                target_set = set(target_markets)
                for idx in range(len(batch)):
                    key_str = str(idx + 1)
                    if key_str in result and isinstance(result[key_str], dict):
                        validated: Dict[str, str] = {}
                        for market, suggested in result[key_str].items():
                            if market in target_set and suggested:
                                # 패션 상품에 어울리지 않는 카테고리 접두어 차단
                                _fashion_exclude = (
                                    "인테리어소품",
                                    "식품",
                                    "출산/육아",
                                    "반려동물",
                                    "자동차용품",
                                    "도서/음반",
                                    "디지털/가전",
                                    "생활/건강",
                                    "스포츠/레저용품",
                                    "여행/숙박",
                                    "e쿠폰/티켓",
                                    "취미/컬렉션",
                                    "수입명품",
                                    "주니어의류",
                                    "아동의류",
                                    "유아의류",
                                    "베이비의류",
                                )
                                if any(
                                    suggested.startswith(p) for p in _fashion_exclude
                                ):
                                    logger.warning(
                                        f"[벌크매핑] '{suggested}' 패션 무관 카테고리 → 스킵"
                                    )
                                    continue
                                # 동기화된 카테고리 목록에 있는지 검증
                                market_cat_list = market_cat_lists.get(market, [])
                                if not market_cat_list or suggested in market_cat_list:
                                    validated[market] = suggested
                                else:
                                    # 유사매칭 시도
                                    fallback = _similarity_match_smartstore(
                                        suggested, market_cat_list
                                    )
                                    if fallback:
                                        logger.warning(
                                            f"[벌크매핑] AI '{suggested}' 목록에 없음 → {fallback}"
                                        )
                                        validated[market] = fallback
                                    else:
                                        logger.warning(
                                            f"[벌크매핑] AI '{suggested}' 목록에 없고 유사매칭 실패 → 스킵"
                                        )
                        all_results.append(validated)
                    else:
                        all_results.append("AI 응답에서 누락")
            except Exception as e:
                logger.error("[벌크매핑] 배치 응답 파싱 실패: %s", e)
                for _ in batch:
                    all_results.append(f"파싱 실패: {e}")

            # 배치 간 딜레이 (분당 토큰 제한 대응)
            if batch_start + batch_size < len(items):
                logger.info(
                    "[벌크매핑] 배치 %d/%d 완료, 5초 대기",
                    batch_start // batch_size + 1,
                    (len(items) + batch_size - 1) // batch_size,
                )
                await asyncio.sleep(5)

        return all_results

    # ==================== AI Category Suggestion ====================

    async def ai_suggest_category(
        self,
        source_site: str,
        source_category: str,
        sample_products: List[str],
        sample_tags: Optional[List[str]] = None,
        target_markets: Optional[List[str]] = None,
        api_key: Optional[str] = None,
    ) -> Dict[str, str]:
        """카테고리 매핑 추천. 룰→유사도→AI 3단계.

        DB에 저장된 마켓 카테고리를 우선 사용하고, 없으면 하드코딩 fallback.
        """
        markets = target_markets or list(MARKET_CATEGORIES.keys())
        result: Dict[str, str] = {}

        # 성별 감지 (상품명, 태그, 카테고리에서 추출)
        gender = _detect_gender(sample_products, sample_tags, source_category)

        # 1단계: 룰 기반 매핑 (모든 마켓)
        for m in markets:
            rule = _rule_match(source_site, source_category, m, gender)
            if rule is not None:
                result[m] = rule
                if rule:
                    logger.info(
                        f"[매핑-룰] {source_site} > {source_category} → {m}: {rule} (성별:{gender})"
                    )

        # 2단계: 유사도 매칭 (룰에서 못 찾은 마켓만)
        for m in markets:
            if m in result:
                continue
            cats = await self._get_market_categories(m)
            if cats:
                sim = _similarity_match_smartstore(source_category, cats)
                if sim:
                    result[m] = sim
                    logger.info(
                        f"[매핑-유사도] {source_site} > {source_category} → {m}: {sim}"
                    )

        # 1~2단계에서 모든 마켓 해결되면 AI 호출 불필요
        remaining_markets = [m for m in markets if m not in result]
        if not remaining_markets:
            return result

        # 3단계: AI 호출 (나머지 마켓만)
        from backend.core.config import settings

        key = api_key or settings.anthropic_api_key
        if not key:
            return result  # AI 키 없으면 1~2단계 결과만 반환

        import anthropic

        # DB 우선 조회 후 하드코딩 fallback
        market_cats: Dict[str, List[str]] = {}
        for m in remaining_markets:
            cats = await self._get_market_categories(m)
            if cats:
                market_cats[m] = cats

        if not market_cats:
            return {}

        # 키워드 추출 — leaf(하위) 키워드 우선, 상위는 보조
        cat_segments = [
            seg.strip() for seg in source_category.split(">") if seg.strip()
        ]
        # leaf 키워드: 마지막 세그먼트 + 태그 + 상품명 단어
        leaf_keywords: set[str] = set()
        if cat_segments:
            leaf_keywords.add(cat_segments[-1])
        for t in sample_tags or []:
            if t and not t.startswith("__") and len(t) >= 2:
                leaf_keywords.add(t)
        for name in sample_products[:3]:
            for word in name.split():
                if len(word) >= 2:
                    leaf_keywords.add(word)
        # 상위 키워드: 카테고리 상위 세그먼트
        parent_keywords = set(seg for seg in cat_segments[:-1] if len(seg) >= 2)

        # 동의어 확장
        leaf_keywords = _expand_synonyms(leaf_keywords)
        parent_keywords = _expand_synonyms(parent_keywords)

        # 필터: 키워드 매칭 개수로 가중치 정렬 — leaf(2점) + parent(1점)
        market_list_parts: list[str] = []
        for market, cats in market_cats.items():
            scored: list[tuple[int, str]] = []
            for c in cats:
                leaf_score = sum(2 for kw in leaf_keywords if kw in c)
                parent_score = sum(1 for kw in parent_keywords if kw in c)
                total = leaf_score + parent_score
                if total > 0:
                    scored.append((total, c))
            scored.sort(key=lambda x: -x[0])
            relevant = [c for _, c in scored[:20]]
            if not relevant:
                relevant = cats[:10]
            market_list_parts.append(
                f"- {market}: {json.dumps(relevant, ensure_ascii=False)}"
            )
        market_list_str = "\n".join(market_list_parts)

        sample_str = ", ".join(sample_products[:3]) if sample_products else "(없음)"
        tag_str = ", ".join(
            [t for t in (sample_tags or []) if not t.startswith("__")][:5]
        )

        # 이미 매핑된 타 마켓 참고 정보 구성
        _ref_lines = ""
        if result:
            _ref_parts = [f"{mk}: {val}" for mk, val in result.items() if val]
            if _ref_parts:
                _ref_lines = (
                    "\n[이미 매핑된 타 마켓 — 참고용]\n"
                    + "\n".join(f"- {p}" for p in _ref_parts)
                    + "\n"
                )

        # 성별 레이블 (프롬프트 힌트용)
        _gender_label = {"male": "남성", "female": "여성", "unisex": "남녀공용"}.get(
            gender, "-"
        )

        # EXPORTED_RULES 기반 학습 예시 구성
        _single_fewshot = _build_fewshot_block(
            [{"site": source_site, "leaf_path": source_category}],
            list(market_cats.keys()),
        )

        prompt = f"""소싱 카테고리를 마켓 카테고리에 매핑.

[소싱] {source_site} | {source_category} | 상품: {sample_str} | 태그: {tag_str or "-"} | 성별: {_gender_label}
{_ref_lines}{_single_fewshot}
[허용된 마켓 카테고리 — 이 중에서만 선택]
{market_list_str}

규칙:
1. 각 마켓별로 위 목록에 있는 카테고리 문자열을 정확히 그대로 복사하여 선택.
2. 목록에 없는 카테고리를 임의로 만들거나 변형하지 마세요.
3. 성별 매칭 최우선: 성별이 "남성"이면 남성 카테고리만, "여성"이면 여성 카테고리만 선택.
4. 소싱 카테고리 경로에 "남성", "맨즈", "남자" 단어가 있으면 반드시 남성 카테고리로 매핑.
5. 소싱 카테고리 경로에 "여성", "우먼즈", "여자" 단어가 있으면 반드시 여성 카테고리로 매핑.
6. 패션 상품(의류/신발/가방)은 "패션의류"·"패션잡화" 대분류 우선. "스포츠/레저"는 소싱에 스포츠 키워드가 있을 때만 선택.
7. 학습 예시가 있으면 동일 대분류·동일 성별 패턴을 따라 매핑하세요.
8. 모든 마켓에 반드시 값을 채우세요. 빈값 금지.
JSON만:
{json.dumps({m: "" for m in market_cats}, ensure_ascii=False)}"""

        logger.info(
            f"[AI매핑] 프롬프트 마켓: {list(market_cats.keys())} ({len(market_cats)}개)"
        )
        for mk, cats_list in market_cats.items():
            leaf_m = [c for c in cats_list if any(kw in c for kw in leaf_keywords)]
            logger.info(
                f"[AI매핑] {mk}: DB {len(cats_list)}개, 키워드매칭 {len(leaf_m)}개"
            )

        client = anthropic.AsyncAnthropic(api_key=key)

        # 429 rate limit 대비 재시도 (최대 3회, 60초 대기)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = await client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=2048,
                    messages=[{"role": "user", "content": prompt}],
                )
                break
            except anthropic.RateLimitError as e:
                if attempt < max_retries - 1:
                    wait = 60 * (attempt + 1)  # 60초, 120초
                    logger.warning(
                        "Claude API 429 rate limit — %d초 후 재시도 (%d/%d)",
                        wait,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error("Claude API rate limit 초과 (재시도 소진): %s", e)
                    raise ValueError(f"Claude API rate limit 초과: {e}") from e

        try:
            # 응답에서 JSON 추출
            text = response.content[0].text.strip()
            # ```json ... ``` 블록 제거
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3].strip()

            ai_result = json.loads(text)
            # AI 응답에서 누락된 마켓 확인
            missing = [m for m in market_cats if m not in ai_result]
            if missing:
                logger.warning(f"[AI매핑] AI 응답에서 누락된 마켓: {missing}")
            logger.info(f"[AI매핑] AI 응답 키: {list(ai_result.keys())}")

            # 응답 검증: 동기화된 카테고리 목록에 있는 것만 수용
            ai_validated: Dict[str, str] = {}
            for market, suggested in ai_result.items():
                if market not in market_cats or not suggested:
                    continue
                if suggested in market_cats[market]:
                    ai_validated[market] = suggested
                    logger.info(f"[AI매핑] {market}: '{suggested}' ✓ 목록에 존재")
                else:
                    # 목록에 없으면 유사매칭 시도 — leaf 키워드 포함 후보 우선
                    fallback_pool = [
                        c
                        for c in market_cats[market]
                        if any(kw in c for kw in leaf_keywords)
                    ]
                    fallback = _similarity_match_smartstore(
                        suggested, fallback_pool or market_cats[market]
                    )
                    if fallback:
                        logger.warning(
                            f"[AI매핑] {market}: '{suggested}' 목록에 없음 → 유사매칭: {fallback}"
                        )
                        ai_validated[market] = fallback
                    else:
                        logger.warning(
                            f"[AI매핑] {market}: '{suggested}' 목록에 없고 유사매칭 실패 → 스킵"
                        )

            # 1~2단계 결과 + AI 검증 결과 병합 (AI로 보충)
            for k, v in ai_validated.items():
                if k not in result:
                    result[k] = v

            # AI가 빠뜨린 마켓은 상품명 키워드로 유사매칭 fallback
            for m in remaining_markets:
                if m not in result and m in market_cats:
                    # 상품명+태그 키워드로 직접 매칭
                    all_kw = leaf_keywords | parent_keywords
                    candidates = [
                        c for c in market_cats[m] if any(kw in c for kw in all_kw)
                    ]
                    if candidates:
                        best = max(
                            candidates, key=lambda c: sum(1 for kw in all_kw if kw in c)
                        )
                        result[m] = best
                        logger.info(f"[AI매핑] {m}: AI 누락 → 키워드 fallback: {best}")

            return result

        except json.JSONDecodeError as e:
            logger.error("AI 응답 JSON 파싱 실패: %s", e)
            return result  # AI 실패해도 1~2단계 결과는 반환
        except anthropic.APIError as e:
            logger.error("Claude API 오류: %s", e)
            return result  # AI 실패해도 1~2단계 결과는 반환

    # ==================== Bulk AI Mapping ====================

    async def bulk_ai_mapping(
        self,
        api_key: str,
        session: "AsyncSession",
        target_markets: Optional[List[str]] = None,
        source_site: Optional[str] = None,
        category_prefix: Optional[str] = None,
    ) -> Dict[str, Any]:
        """미매핑 카테고리 자동 매핑 + 기존 매핑 누락 마켓 보충.

        target_markets: 대상 마켓 (미지정 시 활성 계정 마켓)
        source_site: 소싱사이트 필터 (예: "MUSINSA")
        category_prefix: 카테고리 경로 prefix 필터 (예: "신발")
        """
        from sqlmodel import select
        from backend.domain.samba.collector.model import SambaCollectedProduct

        if target_markets:
            # 사용자가 직접 선택한 마켓
            all_market_keys = set(target_markets) & set(MARKET_CATEGORIES.keys())
            logger.info(
                f"[벌크매핑] 사용자 선택 마켓: {all_market_keys} ({len(all_market_keys)}개)"
            )
        else:
            # 폴백: 활성 계정 마켓
            from backend.domain.samba.account.model import SambaMarketAccount

            acct_stmt = (
                select(SambaMarketAccount.market_type)
                .where(SambaMarketAccount.is_active == True)
                .distinct()
            )
            acct_result = await session.execute(acct_stmt)
            active_markets = {row[0] for row in acct_result.all()}
            if active_markets:
                all_market_keys = active_markets & set(MARKET_CATEGORIES.keys())
                logger.info(
                    f"[벌크매핑] 활성 마켓 대상: {all_market_keys} ({len(all_market_keys)}개)"
                )
            else:
                all_market_keys = set(MARKET_CATEGORIES.keys())

        if not all_market_keys:
            return {
                "mapped": 0,
                "updated": 0,
                "skipped": 0,
                "errors": ["대상 마켓이 없습니다"],
            }

        # 마켓별 동기화된 카테고리 목록 미리 로드 (검증용)
        all_market_cats: Dict[str, List[str]] = {}
        for mk in all_market_keys:
            cats = await self._get_market_categories(mk)
            if cats:
                all_market_cats[mk] = cats

        # 1) 수집 상품에서 고유 (site, leaf_category, 대표 상품명) 추출
        # OOM 방지: 필요한 컬럼만 조회 + source_site 필터 적용
        stmt = select(
            SambaCollectedProduct.source_site,
            SambaCollectedProduct.category,
            SambaCollectedProduct.category1,
            SambaCollectedProduct.category2,
            SambaCollectedProduct.category3,
            SambaCollectedProduct.category4,
            SambaCollectedProduct.name,
            SambaCollectedProduct.tags,
            SambaCollectedProduct.seo_keywords,
            SambaCollectedProduct.group_key,
        )
        if source_site:
            stmt = stmt.where(SambaCollectedProduct.source_site == source_site)
        result = await session.execute(stmt)
        products = result.all()

        # (site, leaf_path) → 태그 + SEO키워드 + 그룹명 + 성별
        cat_samples: Dict[tuple, List[str]] = {}
        cat_tags: Dict[tuple, List[str]] = {}
        cat_seo: Dict[tuple, List[str]] = {}
        cat_groups: Dict[tuple, set[str]] = {}
        cat_sex: Dict[tuple, set[str]] = {}  # p.sex 값 수집
        for p in products:
            site = p.source_site or ""
            if not site:
                continue
            cats = [p.category1, p.category2, p.category3, p.category4]
            cats = [c for c in cats if c]
            if not cats and p.category:
                cats = [c.strip() for c in p.category.split(">") if c.strip()]
            if not cats:
                continue
            leaf_path = " > ".join(cats)
            if category_prefix and not leaf_path.startswith(category_prefix):
                continue
            key = (site, leaf_path)
            if key not in cat_samples:
                cat_samples[key] = []
                # 태그
                tags = [
                    t
                    for t in (getattr(p, "tags", None) or [])
                    if t and not t.startswith("__")
                ]
                cat_tags[key] = tags[:10]
                # SEO 키워드
                cat_seo[key] = []
                # 그룹명
                cat_groups[key] = set()
                # 성별
                cat_sex[key] = set()
            # 상품명 수집 (성별 감지용, 최대 5개)
            if len(cat_samples[key]) < 5:
                cat_samples[key].append(p.name)
            # p.sex 수집 (남성/여성/남녀공용)
            if getattr(p, "sex", None):
                cat_sex[key].add(p.sex)
            # SEO 키워드 수집 (중복 제거)
            for kw in getattr(p, "seo_keywords", None) or []:
                if kw and kw not in cat_seo[key] and len(cat_seo[key]) < 10:
                    cat_seo[key].append(kw)
            # 그룹명 수집
            gk = getattr(p, "group_key", None)
            if gk and len(cat_groups[key]) < 3:
                cat_groups[key].add(gk)

        if not cat_samples:
            return {"mapped": 0, "updated": 0, "skipped": 0, "errors": []}

        # 2) 기존 매핑 전체 조회
        from backend.domain.samba.category.model import SambaCategoryMapping

        existing_mappings = await self.mapping_repo.list_all()
        existing_map: Dict[tuple, SambaCategoryMapping] = {}
        for m in existing_mappings:
            existing_map[(m.source_site, m.source_category)] = m

        mapped = 0
        updated = 0
        skipped = 0
        rule_mapped = 0
        similarity_mapped = 0
        errors: List[str] = []

        # DB 스마트스토어 카테고리 목록 (2단계 유사도 매칭용 — 리프만)
        ss_cats: list[str] = []
        if "smartstore" in all_market_keys:
            ss_cats = _filter_to_leaves(await self._get_market_categories("smartstore"))

        # ── 3단계 매핑 전략 ──
        # AI 호출 대상만 별도 수집
        batch_items: List[Dict[str, Any]] = []
        for (site, leaf_path), samples in cat_samples.items():
            existing = existing_map.get((site, leaf_path))
            current_targets = (existing.target_mappings or {}) if existing else {}
            missing_markets = all_market_keys - set(current_targets.keys())

            if not missing_markets:
                skipped += 1
                continue

            # 성별 감지: p.sex 값 우선, 없으면 상품명+태그+카테고리 기반 감지
            sex_values = cat_sex.get((site, leaf_path), set())
            if "여성" in sex_values and "남성" not in sex_values:
                gender = "female"
            elif "남성" in sex_values and "여성" not in sex_values:
                gender = "male"
            elif sex_values:
                gender = "unisex"
            else:
                tags_for_gender = cat_tags.get((site, leaf_path), [])
                gender = _detect_gender(samples, tags_for_gender, leaf_path)

            # ── 1단계: 룰 기반 매핑 (모든 마켓) ──
            resolved: Dict[str, str] = {}
            for mk in list(missing_markets):
                rule_result = _rule_match(site, leaf_path, mk, gender)
                if rule_result is not None:
                    resolved[mk] = rule_result
                    if rule_result:
                        logger.info(
                            f"[매핑-룰] {site} > {leaf_path} → {mk}: {rule_result} (성별:{gender})"
                        )

            # ── 2단계: 유사도 매칭 (룰에서 못 찾은 마켓만, 롯데ON 제외) ──
            # ESM(지마켓/옥션): SS 매핑이 있으면 SS 결과를 브릿지로 사용
            # 롯데ON은 카테고리 구조가 복잡하여 유사도 매칭이 오히려 오류를 유발 → 룰에서 못 찾으면 AI에 위임
            ss_mapped = current_targets.get("smartstore") or resolved.get(
                "smartstore", ""
            )
            for mk in list(missing_markets):
                if mk in resolved:
                    continue
                if mk == "lotteon":
                    continue
                mk_cats = (
                    ss_cats
                    if mk == "smartstore"
                    else _filter_to_leaves(await self._get_market_categories(mk))
                )
                if mk_cats:
                    # ESM 마켓은 SS 매핑 결과를 브릿지로 사용 (SS 카테고리 이름이 ESM과 더 유사)
                    if mk in ("gmarket", "auction") and ss_mapped:
                        sim_result = _similarity_match_smartstore(ss_mapped, mk_cats)
                        if sim_result:
                            resolved[mk] = sim_result
                            logger.info(
                                f"[매핑-SS브릿지] {leaf_path} → SS:{ss_mapped[:30]} → {mk}: {sim_result}"
                            )
                            continue
                    sim_result = _similarity_match_smartstore(leaf_path, mk_cats)
                    if sim_result:
                        resolved[mk] = sim_result
                        logger.info(
                            f"[매핑-유사도] {site} > {leaf_path} → {mk}: {sim_result}"
                        )

            # 1~2단계에서 해결된 마켓 저장
            if resolved:
                if existing:
                    new_targets = {**current_targets, **resolved}
                    try:
                        await self.update_mapping(
                            existing.id, {"target_mappings": new_targets}
                        )
                        updated += 1
                    except Exception as e:
                        errors.append(f"[저장실패] {site} > {leaf_path}: {e}")
                else:
                    try:
                        await self.create_mapping(
                            {
                                "source_site": site,
                                "source_category": leaf_path,
                                "target_mappings": resolved,
                            }
                        )
                        mapped += 1
                    except Exception as e:
                        errors.append(f"[저장실패] {site} > {leaf_path}: {e}")
                    # create 후 existing_map 갱신 (AI 단계에서 참조)
                    new_existing = await self.mapping_repo.find_by_async(
                        source_site=site, source_category=leaf_path
                    )
                    if new_existing:
                        existing = new_existing
                        existing_map[(site, leaf_path)] = new_existing
                        current_targets = new_existing.target_mappings or {}

                if resolved:
                    cnt = len(resolved)
                    rule_mapped += cnt
                    missing_markets -= set(resolved.keys())

            # ── 3단계: 나머지 마켓은 AI에 위임 ──
            if missing_markets:
                # AI에 SS 매핑 결과 전달 (ESM 정확도 향상용)
                ss_hint = current_targets.get("smartstore") or resolved.get(
                    "smartstore", ""
                )
                # 이미 매핑된 타 마켓 정보를 AI 참고용으로 전달
                _all_resolved = {**current_targets, **resolved}
                mapped_refs = {
                    mk: val
                    for mk, val in _all_resolved.items()
                    if val and mk not in missing_markets
                }
                batch_items.append(
                    {
                        "site": site,
                        "leaf_path": leaf_path,
                        "samples": samples,
                        "tags": cat_tags.get((site, leaf_path), []),
                        "seo": cat_seo.get((site, leaf_path), []),
                        "groups": list(cat_groups.get((site, leaf_path), set())),
                        "gender": gender,
                        "ss_mapped": ss_hint,
                        "mapped_refs": mapped_refs,
                        "target_markets": list(missing_markets),
                        "existing": existing,
                        "mode": "update" if existing else "create",
                    }
                )

        logger.info(
            f"[벌크매핑] 1~2단계 완료: 룰/유사도={rule_mapped}건, AI대상={len(batch_items)}건, 스킵={skipped}건"
        )

        if not batch_items:
            return {
                "mapped": mapped,
                "updated": updated,
                "skipped": skipped,
                "rule_mapped": rule_mapped,
                "errors": errors,
            }

        # 배치 AI 호출 + 빈 결과 재시도 (최대 2회)
        remaining_items = batch_items
        for round_num in range(2):
            if not remaining_items:
                break

            batch_results = await self._batch_ai_suggest(
                remaining_items,
                list(all_market_keys),
                api_key,
            )

            retry_items: List[Dict[str, Any]] = []

            for item, ai_result in zip(remaining_items, batch_results):
                site = item["site"]
                leaf_path = item["leaf_path"]

                if isinstance(ai_result, str):
                    if round_num == 0:
                        retry_items.append(item)
                        logger.warning(
                            f"[벌크매핑] 에러 → 재시도 대기: {site} > {leaf_path}: {ai_result}"
                        )
                    else:
                        errors.append(
                            f"[{item['mode']}] {site} > {leaf_path}: {ai_result}"
                        )
                    continue

                if item["mode"] == "update":
                    existing = item["existing"]
                    # DB에서 최신 target_mappings 다시 로드 (1~2단계 결과 반영)
                    refreshed = await self.mapping_repo.get_async(existing.id)
                    current_targets = (
                        refreshed.target_mappings
                        if refreshed
                        else existing.target_mappings
                    ) or {}
                    new_targets = {**current_targets}
                    for market, cat in ai_result.items():
                        if cat:
                            new_targets[market] = cat
                    # 새로 추가된 마켓이 없으면 빈 결과
                    if new_targets == current_targets:
                        if round_num == 0:
                            retry_items.append(item)
                        else:
                            errors.append(f"[보충] {site} > {leaf_path}: AI 빈 응답")
                        continue
                    try:
                        await self.update_mapping(
                            existing.id, {"target_mappings": new_targets}
                        )
                        updated += 1
                    except Exception as e:
                        errors.append(f"[보충] {site} > {leaf_path}: {e}")
                else:
                    target_mappings = {m: c for m, c in ai_result.items() if c}
                    if target_mappings:
                        try:
                            await self.create_mapping(
                                {
                                    "source_site": site,
                                    "source_category": leaf_path,
                                    "target_mappings": target_mappings,
                                }
                            )
                            mapped += 1
                        except Exception as e:
                            errors.append(f"[신규] {site} > {leaf_path}: {e}")
                    else:
                        if round_num == 0:
                            retry_items.append(item)
                        else:
                            errors.append(
                                f"[신규] {site} > {leaf_path}: AI 빈 응답 (2회 실패)"
                            )

            remaining_items = retry_items
            if retry_items and round_num == 0:
                logger.info(f"[벌크매핑] {len(retry_items)}개 빈 결과 재시도")
                await asyncio.sleep(3)

        # ── ESM 크로스매핑 자동 적용 ──
        # 지마켓/옥션 중 하나만 매핑된 경우 반대쪽 자동 복사
        esm_pair = {"gmarket", "auction"}
        if esm_pair & all_market_keys:
            esm_copied = 0
            for from_mk, to_mk in [("gmarket", "auction"), ("auction", "gmarket")]:
                if from_mk in all_market_keys and to_mk in all_market_keys:
                    try:
                        cross_result = await self.copy_esm_cross_mapping(
                            from_market=from_mk,
                            to_market=to_mk,
                        )
                        esm_copied += cross_result.get("copied", 0)
                    except Exception as e:
                        logger.warning("[벌크매핑] ESM 크로스매핑 실패: %s", e)
            if esm_copied:
                logger.info("[벌크매핑] ESM 크로스매핑 자동 적용: %d건", esm_copied)
                updated += esm_copied

        return {
            "mapped": mapped,
            "updated": updated,
            "skipped": skipped,
            "rule_mapped": rule_mapped,
            "errors": errors,
        }
