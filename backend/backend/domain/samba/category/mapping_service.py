"""카테고리 매핑 CRUD + 해결 로직 Mixin."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.samba.category.model import SambaCategoryMapping
from backend.domain.samba.category.rules import _OVERSEAS_KEYWORDS

logger = logging.getLogger(__name__)


class CategoryMappingMixin:
    """카테고리 매핑 CRUD + 코드 해결 + 불량 매핑 수정."""

    # 패션/스포츠 상품에 절대 사용 불가한 금지 카테고리 접두어
    _BAD_CATEGORY_PREFIXES = (
        "도서/음반",
        "식품",
        "반려동물",
        "디지털/가전",
        "자동차",
        "출산/육아",
        "여행",
        "인테리어",
        "생활/건강",
        "전자책",
        "완구/취미",
        "문구/사무",
    )

    # ==================== Category Mappings ====================

    async def list_mappings(
        self, skip: int = 0, limit: int = 10000
    ) -> List[SambaCategoryMapping]:
        return await self.mapping_repo.list_async(
            skip=skip, limit=limit, order_by="-created_at"
        )

    async def create_mapping(self, data: Dict[str, Any]) -> SambaCategoryMapping:
        return await self.mapping_repo.create_async(**data)

    async def update_mapping(
        self, mapping_id: str, data: Dict[str, Any]
    ) -> Optional[SambaCategoryMapping]:
        return await self.mapping_repo.update_async(mapping_id, **data)

    async def delete_mapping(self, mapping_id: str) -> bool:
        return await self.mapping_repo.delete_async(mapping_id)

    async def find_mapping(
        self, source_site: str, source_category: str
    ) -> Optional[SambaCategoryMapping]:
        return await self.mapping_repo.find_mapping(source_site, source_category)

    # ==================== ESM 크로스매핑 복사 ====================

    async def copy_esm_cross_mapping(
        self,
        from_market: str = "gmarket",
        to_market: str = "auction",
        mapping_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """지마켓↔옥션 카테고리 매핑을 크로스매핑으로 복사.

        from_market에 매핑이 있고 to_market에 없는 행만 대상.
        경로 → 숫자코드 → 크로스매핑 → 역조회(경로) 순으로 변환.

        Args:
            from_market: 원본 마켓 (기본: gmarket)
            to_market: 대상 마켓 (기본: auction)
            mapping_ids: 대상 매핑 ID 목록 (None이면 전체)

        Returns:
            {"copied": 복사된 수, "skipped": 스킵된 수, "failed": 실패 수}
        """
        from backend.domain.samba.proxy.esmplus import esm_map_category

        # 원본/대상 카테고리 트리 (경로↔코드 변환용)
        from_tree = await self.tree_repo.get_by_site(from_market)
        to_tree = await self.tree_repo.get_by_site(to_market)
        if not from_tree or not from_tree.cat2 or not to_tree or not to_tree.cat2:
            return {
                "copied": 0,
                "skipped": 0,
                "failed": 0,
                "error": "카테고리 트리가 동기화되지 않았습니다",
            }

        from_code_map = from_tree.cat2  # {경로: 코드}
        to_code_map = to_tree.cat2  # {경로: 코드}
        # 역방향 맵: 코드 → 경로
        to_reverse = {str(v): k for k, v in to_code_map.items()}

        # 전체 매핑 조회
        all_mappings = await self.mapping_repo.list_async(
            skip=0, limit=100000, order_by="-created_at"
        )

        copied = 0
        skipped = 0
        failed = 0

        for mapping in all_mappings:
            # mapping_ids 지정 시 해당 ID만 대상
            if mapping_ids and mapping.id not in mapping_ids:
                continue

            targets = mapping.target_mappings or {}

            # 원본 마켓 매핑이 없으면 스킵
            from_path = targets.get(from_market, "")
            if not from_path:
                skipped += 1
                continue

            # 대상 마켓에 이미 매핑이 있으면 스킵
            if targets.get(to_market):
                skipped += 1
                continue

            # 경로 → 숫자코드 변환
            from_code = str(from_code_map.get(from_path, ""))
            if not from_code:
                # 퍼지 매칭 시도
                from_code = await self.resolve_category_code(from_market, from_path)
            if not from_code:
                failed += 1
                logger.warning(
                    "[ESM 크로스복사] %s 코드 변환 실패: %s", from_market, from_path
                )
                continue

            # 크로스매핑: 지마켓 코드 → 옥션 코드
            to_code = esm_map_category(from_code, from_market, to_market)
            if not to_code:
                failed += 1
                logger.warning(
                    "[ESM 크로스복사] 크로스매핑 실패: %s(%s)", from_market, from_code
                )
                continue

            # 숫자코드 → 경로 역조회
            to_path = to_reverse.get(str(to_code), "")
            if not to_path:
                failed += 1
                logger.warning(
                    "[ESM 크로스복사] %s 경로 역조회 실패: %s", to_market, to_code
                )
                continue

            # 매핑 업데이트
            updated_targets = {**targets, to_market: to_path}
            await self.mapping_repo.update_async(
                mapping.id, target_mappings=updated_targets
            )
            copied += 1
            logger.info(
                "[ESM 크로스복사] %s → %s: %s → %s",
                from_market,
                to_market,
                from_path,
                to_path,
            )

        await self.mapping_repo.session.commit()
        return {"copied": copied, "skipped": skipped, "failed": failed}

    # ==================== 카테고리 코드 해결 ====================

    async def resolve_category_code(self, market_type: str, category_path: str) -> str:
        """경로 문자열 → 마켓 숫자 코드 변환. cat2에 저장된 코드맵 사용.

        매칭 우선순위:
        1. 정확 매칭
        2. 마지막 세그먼트 키워드 기반 퍼지 매칭 (leaf 카테고리 유사도)
        """
        tree = await self.tree_repo.get_by_site(market_type)
        if not tree or not tree.cat2:
            return ""
        code_map = tree.cat2
        # 1. 정확 매칭 (리프인 경우만 즉시 반환 — 비-리프이면 prefix 매칭으로 fall-through)
        if category_path in code_map:
            prefix = category_path + " > "
            if not any(p.startswith(prefix) for p in code_map):
                return str(code_map[category_path])

        # 1.5. Prefix 매칭 — 입력이 부모 경로인 경우 (3단계 → 4단계 leaf 검색)
        # 예: "패션의류 > 남성의류 > 바지" → "패션의류 > 남성의류 > 바지 > 청바지" 코드 반환
        prefix = category_path + " > "
        prefix_matches = {
            path: code for path, code in code_map.items() if path.startswith(prefix)
        }
        if prefix_matches:
            best_prefix_path = min(prefix_matches.keys(), key=len)
            logger.info(
                "[카테고리 코드] prefix 매칭: '%s' → '%s' (%s)",
                category_path,
                best_prefix_path,
                prefix_matches[best_prefix_path],
            )
            return str(prefix_matches[best_prefix_path])

        # 2. 키워드 기반 퍼지 매칭
        # 입력 경로의 세그먼트 추출 (예: "패션의류 > 남성의류 > 아우터/코트")
        input_segments = [s.strip() for s in category_path.split(">") if s.strip()]
        if not input_segments:
            return ""

        # 마지막 세그먼트의 키워드 추출 (슬래시 분리 포함)
        last_seg = input_segments[-1]
        input_keywords = set()
        for part in last_seg.replace("/", " ").replace(",", " ").split():
            if len(part) >= 2:
                input_keywords.add(part)
        # 상위 세그먼트 키워드도 추가 (낮은 가중치용)
        parent_keywords = set()
        for seg in input_segments[:-1]:
            for part in seg.replace("/", " ").replace(",", " ").split():
                if len(part) >= 2:
                    parent_keywords.add(part)

        if not input_keywords:
            return ""

        best_code = ""
        best_score = 0
        for path, code in code_map.items():
            # 해외 카테고리는 퍼지 매칭에서 제외 — 기존 DB에 해외 코드가 있어도 선택 안됨
            if any(kw in path for kw in _OVERSEAS_KEYWORDS):
                continue
            path_segments = [s.strip() for s in path.split(">") if s.strip()]
            if not path_segments:
                continue
            path_last = path_segments[-1]
            path_keywords = set()
            for part in path_last.replace("/", " ").replace(",", " ").split():
                if len(part) >= 2:
                    path_keywords.add(part)

            # 마지막 세그먼트 키워드 겹침 점수
            overlap = len(input_keywords & path_keywords)
            if overlap == 0:
                continue
            score = overlap * 10

            # 상위 세그먼트 키워드 보너스 (가중치 상향: 3 → 5)
            path_all_keywords = set()
            for seg in path_segments[:-1]:
                for part in seg.replace("/", " ").replace(",", " ").split():
                    if len(part) >= 2:
                        path_all_keywords.add(part)
            parent_overlap = len(parent_keywords & path_all_keywords)
            score += parent_overlap * 5

            # 대분류(첫 세그먼트) 일치 보너스 — 골프의류 vs 패션의류 구분
            if input_segments and path_segments:
                if input_segments[0] == path_segments[0]:
                    score += 15

            # 세그먼트 깊이 유사도 보너스
            depth_diff = abs(len(input_segments) - len(path_segments))
            if depth_diff == 0:
                score += 5
            elif depth_diff == 1:
                score += 2

            if score > best_score:
                best_score = score
                best_code = str(code)

        if best_code:
            logger.info(
                "[카테고리 코드] 퍼지 매칭: '%s' → %s (score=%d)",
                category_path,
                best_code,
                best_score,
            )
            return best_code

        # 3. 비-리프 폴백: 하위 리프 카테고리 중 최적 선택
        prefix = category_path + " > "
        descendants = {p: c for p, c in code_map.items() if p.startswith(prefix)}
        if descendants:
            # 리프만 추출 (하위 자식이 없는 경로)
            leaf_descs = [
                (p, c)
                for p, c in descendants.items()
                if not any(d.startswith(p + " > ") for d in descendants)
            ]
            if leaf_descs:
                # "기타" 하위 카테고리 우선
                for p, c in leaf_descs:
                    last_seg = p.split(" > ")[-1]
                    if "기타" in last_seg:
                        logger.info(
                            "[카테고리 코드] 비-리프 → 기타: '%s' → %s (%s)",
                            category_path,
                            c,
                            p,
                        )
                        return str(c)
                # 없으면 최단 경로(가장 직접적인 하위) 선택
                leaf_descs.sort(key=lambda x: len(x[0]))
                logger.info(
                    "[카테고리 코드] 비-리프 → 리프: '%s' → %s (%s)",
                    category_path,
                    leaf_descs[0][1],
                    leaf_descs[0][0],
                )
                return str(leaf_descs[0][1])

        return ""

    # ==================== 불량 카테고리 감지 & 재매핑 ====================

    def _is_bad_mapping(self, path: str) -> bool:
        """카테고리 경로가 금지 카테고리로 시작하는지 확인."""
        if not path:
            return False
        return any(path.startswith(prefix) for prefix in self._BAD_CATEGORY_PREFIXES)

    async def fix_bad_mappings(
        self,
        api_key: str,
        session: "AsyncSession",
        target_markets: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """불량 카테고리 매핑을 감지하고 AI 재매핑한다.

        불량 기준: 11번가 등 마켓 타겟이 패션과 무관한 카테고리(도서/음반, 식품 등)로
        매핑된 경우.
        해당 마켓의 타겟값만 초기화한 뒤 bulk_ai_mapping으로 재매핑한다.
        """
        # 1) 전체 매핑 조회
        all_mappings = await self.mapping_repo.list_all()

        bad_found: List[Dict[str, Any]] = []
        fixed_count = 0
        errors: List[str] = []

        # 2) 불량 매핑 감지 및 해당 마켓 타겟값 초기화
        for mapping in all_mappings:
            targets: Dict[str, str] = mapping.target_mappings or {}
            bad_markets = [
                market for market, path in targets.items() if self._is_bad_mapping(path)
            ]
            if not bad_markets:
                continue

            # 불량 마켓만 필터링하여 기록
            bad_found.append(
                {
                    "id": mapping.id,
                    "source_site": mapping.source_site,
                    "source_category": mapping.source_category,
                    "bad_markets": {m: targets[m] for m in bad_markets},
                }
            )

            # 불량 마켓 타겟값만 제거 (나머지 올바른 매핑은 유지)
            new_targets = {k: v for k, v in targets.items() if k not in bad_markets}
            try:
                await self.mapping_repo.update_async(
                    mapping.id, target_mappings=new_targets
                )
                fixed_count += 1
                logger.info(
                    "[불량매핑] 초기화: %s > %s → 제거 마켓: %s",
                    mapping.source_site,
                    mapping.source_category,
                    bad_markets,
                )
            except Exception as e:
                errors.append(f"{mapping.source_site} > {mapping.source_category}: {e}")

        if not bad_found:
            return {
                "detected": 0,
                "fixed": 0,
                "remapped": 0,
                "bad_list": [],
                "errors": errors,
                "message": "불량 카테고리가 없습니다.",
            }

        logger.info(
            "[불량매핑] 감지=%d건, 초기화=%d건 — AI 재매핑 시작",
            len(bad_found),
            fixed_count,
        )

        # 3) 초기화된 카테고리들을 AI 재매핑
        remap_result = await self.bulk_ai_mapping(
            api_key=api_key,
            session=session,
            target_markets=target_markets,
        )

        return {
            "detected": len(bad_found),
            "fixed": fixed_count,
            "remapped": remap_result.get("mapped", 0) + remap_result.get("updated", 0),
            "bad_list": bad_found,
            "errors": errors + remap_result.get("errors", []),
            "message": f"{len(bad_found)}개 불량 매핑 감지 → {fixed_count}개 초기화 → AI 재매핑 완료",
        }
