"""Brand Risk System — 사건DB/별칭 레포지토리 (Phase 1: 최소 기반만).

BaseRepository 를 그대로 상속해 forbidden/repository.py 와 동일한 컨벤션을
따른다. 이번 Phase 에서는 어떤 전송/등록 경로에서도 호출하지 않는다 — 아직
데이터가 없고(MASTER/CASE 적재는 Phase 2), 실제 판정에 쓰기 시작하는 것도
이후 Phase 몫이다.
"""

from typing import List, Optional

from sqlmodel import select

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.brand.alias_model import SambaBrandAlias, normalize_alias_key
from backend.domain.samba.brand.risk_case_model import SambaBrandRiskCase


class SambaBrandRiskCaseRepository(BaseRepository[SambaBrandRiskCase]):
    def __init__(self, session):
        super().__init__(session, SambaBrandRiskCase)

    async def list_by_normalized_brand(
        self, normalized_brand: str
    ) -> List[SambaBrandRiskCase]:
        return await self.filter_by_async(
            normalized_brand=normalized_brand,
            order_by="incident_date",
            order_by_desc=True,
        )

    async def count_by_normalized_brand(self, normalized_brand: str) -> int:
        """evidence_count 는 컬럼으로 저장하지 않고 매번 실제 사건 수를 센다.

        수동 정수 컬럼은 사건이 새로 쌓여도 갱신을 깜빡하면 그 순간부터 거짓말을
        하게 된다(soul.md 추측 금지 원칙). 지금 스케일(사건 수백~수천 건대)에서는
        COUNT 쿼리 비용이 무시할 만하다 — 나중에 정말 느려지면 그때 캐시 컬럼을
        추가하되 이름에 반드시 `_cache` 를 붙여 "derived, 신뢰 원본 아님"을
        명시한다.
        """
        return await self.count_async(filters={"normalized_brand": normalized_brand})


class SambaBrandAliasRepository(BaseRepository[SambaBrandAlias]):
    def __init__(self, session):
        super().__init__(session, SambaBrandAlias)

    async def find_by_alias_key(
        self, alias_key: str, tenant_id: Optional[str] = None
    ) -> Optional[SambaBrandAlias]:
        stmt = select(SambaBrandAlias).where(SambaBrandAlias.alias_key == alias_key)
        if tenant_id is not None:
            stmt = stmt.where(
                (SambaBrandAlias.tenant_id == tenant_id)
                | (SambaBrandAlias.tenant_id.is_(None))
            )
        else:
            stmt = stmt.where(SambaBrandAlias.tenant_id.is_(None))
        result = await self.session.execute(stmt.limit(1))
        return result.scalars().first()


async def resolve_canonical_key(
    session, raw_brand: str, tenant_id: Optional[str] = None
) -> str:
    """표기변형을 canonical 브랜드 키로 해석한다.

    alias 테이블에 매칭되는 등록이 있으면 그 canonical_key 를, 없으면
    (아직 alias 로 등록 안 된 브랜드는) 정규화된 자기 자신을 canonical 로
    취급한다 — "alias 미등록 = 독자 브랜드"가 기본값이다.
    """
    key = normalize_alias_key(raw_brand)
    if not key:
        return ""
    repo = SambaBrandAliasRepository(session)
    alias = await repo.find_by_alias_key(key, tenant_id=tenant_id)
    return alias.canonical_key if alias else key
