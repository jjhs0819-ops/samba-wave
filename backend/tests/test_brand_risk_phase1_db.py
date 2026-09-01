"""Brand Risk System Phase 1 — DB 통합 테스트 (@pytest.mark.integration).

실제 DB 세션(backend.db.orm.get_write_session)을 쓰지만 **절대 commit 하지
않는다** — session.flush() 로 같은 트랜잭션 안에서만 보이게 하고, 테스트
함수가 끝나면 get_write_session() 의 finally 블록이 커밋 안 된 트랜잭션을
자동 rollback 한다(backend/backend/db/orm.py). 그래서 이 테스트는 어떤 DB를
가리키든(로컬 복제본이든 실수로 다른 DB든) 흔적을 남기지 않는다.

실행 방법 (기본 backend/.env 는 이 환경에서 연결 불가 — WRITE_DB_PORT=5433
에 아무것도 안 떠 있음, 이번 Phase와 무관한 기존 이슈):

    WRITE_DB_HOST=127.0.0.1 WRITE_DB_PORT=5432 WRITE_DB_NAME=<db> \
    WRITE_DB_USER=samba WRITE_DB_PASSWORD=<pw> \
    READ_DB_HOST=127.0.0.1 READ_DB_PORT=5432 READ_DB_NAME=<db> \
    READ_DB_USER=samba READ_DB_PASSWORD=<pw> \
    .venv/Scripts/python -m pytest tests/test_brand_risk_phase1_db.py -m integration

DB 에 연결이 안 되면 각 테스트는 실패가 아니라 skip 된다(환경 문제와 로직
결함을 구분하기 위함).
"""

from datetime import date
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytestmark = pytest.mark.integration


async def _get_session_or_skip():
    """SQLAlchemy 세션은 지연 연결이라 __aenter__ 만으로는 연결 실패가 안 드러난다
    (첫 쿼리에서야 에러) — 여기서 SELECT 1 로 강제로 연결을 확인해야 미연결 환경에서
    테스트가 FAILED 가 아니라 SKIPPED 로 뜬다(환경 문제와 로직 결함을 구분).
    """
    from sqlalchemy import text

    from backend.db.orm import get_write_session

    cm = get_write_session()
    session = await cm.__aenter__()
    try:
        await session.execute(text("SELECT 1"))
    except Exception as e:  # noqa: BLE001 — 환경 문제(DB 미기동 등)는 skip
        await cm.__aexit__(type(e), e, e.__traceback__)
        pytest.skip(f"DB 연결 불가 — 환경 문제로 skip: {e}")
    return cm, session


class TestExistingBrandGuardRegression:
    """마이그레이션 전후 기존 3건의 BrandGuard 판정이 동일한지 회귀 확인.

    2026-08 데이터 감사에서 확보한 Before 스냅샷과 대조한다:
      하바이아나스: allowed, coupang_uid_required=False, coupang_matched=True
      퍼글러      : allowed, coupang_uid_required=False, coupang_matched=True
      브룩스      : blocked, coupang_uid_required=True,  coupang_matched=True
    """

    _BEFORE = {
        "하바이아나스": {
            "verdict": "allowed",
            "coupang_uid_required": False,
            "coupang_matched": True,
        },
        "퍼글러": {
            "verdict": "allowed",
            "coupang_uid_required": False,
            "coupang_matched": True,
        },
        "브룩스": {
            "verdict": "blocked",
            "coupang_uid_required": True,
            "coupang_matched": True,
        },
    }

    @pytest.mark.asyncio
    async def test_existing_rows_verdict_unchanged(self) -> None:
        """기존 3건은 tenant_id 가 채워진 행이라, check() 에 그 tenant_id 를
        그대로 넘겨야 _load_index() 의 tenant 필터에 걸린다(brand/service.py
        L83-92 — tenant_id=None 으로 부르면 전역 행만 보여 이 행 자체가
        안 보인다). DB 마다 실제 tenant_id 가 다를 수 있어 하드코딩하지 않고
        행에서 그대로 읽어 되돌려준다.
        """
        from sqlmodel import select

        from backend.domain.samba.brand.model import SambaBrandRestriction
        from backend.domain.samba.brand.service import BrandGuardService

        cm, session = await _get_session_or_skip()
        try:
            guard = BrandGuardService(session)
            for brand, expected in self._BEFORE.items():
                row = (
                    (
                        await session.execute(
                            select(SambaBrandRestriction).where(
                                SambaBrandRestriction.brand == brand
                            )
                        )
                    )
                    .scalars()
                    .one()
                )
                result = await guard.check(
                    brand,
                    coupang_client=None,
                    record=False,
                    tenant_id=row.tenant_id,
                )
                assert result.verdict == expected["verdict"], (
                    f"{brand} verdict 이 마이그레이션으로 바뀜: "
                    f"{expected['verdict']} -> {result.verdict}"
                )
        finally:
            await cm.__aexit__(None, None, None)

    @pytest.mark.asyncio
    async def test_existing_rows_new_axes_are_null(self) -> None:
        """기존 3건은 신규 축을 아직 아무도 채운 적이 없으니 전부 NULL 이어야 한다."""
        from sqlmodel import select

        from backend.domain.samba.brand.model import SambaBrandRestriction

        cm, session = await _get_session_or_skip()
        try:
            stmt = select(SambaBrandRestriction).where(
                SambaBrandRestriction.brand.in_(list(self._BEFORE.keys()))
            )
            rows = (await session.execute(stmt)).scalars().all()
            assert len(rows) == 3
            for row in rows:
                assert row.ip_risk_level is None
                assert row.coupang_pre_auth is None
                assert row.marq_vision is None
                assert row.marketplace_risk is None
                assert row.image_risk_note is None
                assert row.confidence is None
        finally:
            await cm.__aexit__(None, None, None)


class TestNewAxesExpressiveness:
    """신규 축이 실제로 표현하고자 했던 조합을 저장·조회할 수 있는지 확인.

    (실 DB row 를 변경하지 않도록 별도 테스트 브랜드 키를 쓴다 — rollback
    되긴 하지만 실제 브랜드명과 섞이지 않게 하는 게 더 안전하다.)
    """

    @pytest.mark.asyncio
    async def test_brooks_pattern_ip_risk_and_pre_auth_independent(self) -> None:
        """브룩스 실사례 패턴: ip_risk=NO_RISK_FOUND 이면서 coupang_pre_auth=REQUIRED."""
        from backend.domain.samba.brand.model import (
            SambaBrandRestriction,
            normalize_brand,
        )
        from backend.domain.samba.brand.risk_constants import (
            COUPANG_PRE_AUTH_REQUIRED,
            IP_RISK_NO_RISK_FOUND,
        )

        cm, session = await _get_session_or_skip()
        try:
            brand = "__TEST_BROOKS_PATTERN__"
            row = SambaBrandRestriction(
                brand=brand,
                brand_key=normalize_brand(brand),
                verdict="blocked",  # 기존 verdict 는 여전히 안전 우선으로 채움
                source="manual",
                ip_risk_level=IP_RISK_NO_RISK_FOUND,
                coupang_pre_auth=COUPANG_PRE_AUTH_REQUIRED,
            )
            session.add(row)
            await session.flush()

            from sqlmodel import select

            stmt = select(SambaBrandRestriction).where(
                SambaBrandRestriction.brand_key == normalize_brand(brand)
            )
            fetched = (await session.execute(stmt)).scalars().one()
            assert fetched.ip_risk_level == IP_RISK_NO_RISK_FOUND
            assert fetched.coupang_pre_auth == COUPANG_PRE_AUTH_REQUIRED
            # 단일 verdict 축으로는 표현 못 했던 조합이 동시에 저장됐는지가 핵심
            assert fetched.ip_risk_level != fetched.coupang_pre_auth
        finally:
            await cm.__aexit__(None, None, None)

    @pytest.mark.asyncio
    async def test_descente_marketplace_risk_per_market(self) -> None:
        """데상트 패턴: 마켓별로 다른 IP Risk 등급을 동시에 저장."""
        from backend.domain.samba.brand.model import (
            SambaBrandRestriction,
            normalize_brand,
        )
        from backend.domain.samba.brand.risk_constants import (
            IP_RISK_BLOCK,
            IP_RISK_BLOCK_STRONG,
            IP_RISK_UNKNOWN,
        )

        cm, session = await _get_session_or_skip()
        try:
            brand = "__TEST_DESCENTE_PATTERN__"
            row = SambaBrandRestriction(
                brand=brand,
                brand_key=normalize_brand(brand),
                verdict="blocked",
                source="manual",
                ip_risk_level=IP_RISK_BLOCK_STRONG,
                marketplace_risk={
                    "coupang": IP_RISK_BLOCK,
                    "lotteon": IP_RISK_BLOCK,
                    "smartstore": IP_RISK_UNKNOWN,
                    "elevenst": IP_RISK_UNKNOWN,
                },
            )
            session.add(row)
            await session.flush()

            from sqlmodel import select

            stmt = select(SambaBrandRestriction).where(
                SambaBrandRestriction.brand_key == normalize_brand(brand)
            )
            fetched = (await session.execute(stmt)).scalars().one()
            assert fetched.marketplace_risk["coupang"] == IP_RISK_BLOCK
            assert fetched.marketplace_risk["lotteon"] == IP_RISK_BLOCK
            assert fetched.marketplace_risk["smartstore"] == IP_RISK_UNKNOWN
            assert fetched.marketplace_risk["elevenst"] == IP_RISK_UNKNOWN
        finally:
            await cm.__aexit__(None, None, None)


class TestBrandAliasResolution:
    @pytest.mark.asyncio
    async def test_arcteryx_variants_resolve_to_same_canonical(self) -> None:
        from backend.domain.samba.brand.alias_model import (
            SambaBrandAlias,
            normalize_alias_key,
        )
        from backend.domain.samba.brand.risk_repository import resolve_canonical_key

        cm, session = await _get_session_or_skip()
        try:
            canonical = normalize_alias_key("ARC'TERYX")
            session.add(
                SambaBrandAlias(
                    canonical_key=canonical,
                    alias_raw="ARC`TERYX",
                    alias_key=normalize_alias_key("ARC`TERYX"),
                    note="2026-08 데이터 감사에서 확인된 표기 오타",
                )
            )
            await session.flush()

            resolved_backtick = await resolve_canonical_key(session, "ARC`TERYX")
            resolved_apostrophe = await resolve_canonical_key(session, "ARC'TERYX")
            resolved_curly = await resolve_canonical_key(session, "ARC’TERYX")

            assert resolved_backtick == canonical
            # alias 로 등록 안 한 정식 표기는 자기 자신을 canonical 로 취급
            assert resolved_apostrophe == canonical
            assert resolved_curly == canonical
        finally:
            await cm.__aexit__(None, None, None)

    @pytest.mark.asyncio
    async def test_puma_and_puma_bodywear_do_not_share_alias(self) -> None:
        from backend.domain.samba.brand.risk_repository import resolve_canonical_key

        cm, session = await _get_session_or_skip()
        try:
            puma = await resolve_canonical_key(session, "PUMA")
            puma_bodywear = await resolve_canonical_key(session, "PUMA BODYWEAR")
            assert puma != puma_bodywear
        finally:
            await cm.__aexit__(None, None, None)


class TestLegacyConflictDetection:
    @pytest.mark.asyncio
    async def test_arcteryx_forbidden_word_vs_no_risk_pre_auth_flags_conflict(
        self,
    ) -> None:
        """레거시(forbidden_word 전체마켓 차단) + 신규축(NO_RISK_FOUND+REQUIRED)
        조합이면 LEGACY_CONFLICT 로 잡혀야 한다 — 실제 ARC`TERYX 패턴 재현."""
        from backend.domain.samba.brand.legacy_conflict import check_legacy_conflict
        from backend.domain.samba.brand.model import (
            SambaBrandRestriction,
            normalize_brand,
        )
        from backend.domain.samba.brand.risk_constants import (
            COUPANG_PRE_AUTH_REQUIRED,
            IP_RISK_NO_RISK_FOUND,
        )
        from backend.domain.samba.forbidden.model import SambaForbiddenWord

        cm, session = await _get_session_or_skip()
        try:
            brand = "__TEST_LEGACY_CONFLICT_BRAND__"
            session.add(
                SambaForbiddenWord(
                    word=brand,
                    type="forbidden",
                    scope="title",
                    market=None,  # 전체마켓
                    is_active=True,
                )
            )
            session.add(
                SambaBrandRestriction(
                    brand=brand,
                    brand_key=normalize_brand(brand),
                    verdict="blocked",
                    source="manual",
                    ip_risk_level=IP_RISK_NO_RISK_FOUND,
                    coupang_pre_auth=COUPANG_PRE_AUTH_REQUIRED,
                )
            )
            await session.flush()

            conflict = await check_legacy_conflict(session, brand)
            assert conflict is not None
            assert conflict.ip_risk_level == IP_RISK_NO_RISK_FOUND
            assert conflict.coupang_pre_auth == COUPANG_PRE_AUTH_REQUIRED
        finally:
            await cm.__aexit__(None, None, None)

    @pytest.mark.asyncio
    async def test_no_conflict_when_new_axes_empty(self) -> None:
        """Phase 2(MASTER 적재) 전인 지금은 신규 축이 비어 있으므로 항상 None.

        실제 ARC`TERYX 자체로 확인 — forbidden_word 에는 있지만(2026-08 감사
        확인) brand_restriction 에 신규 축 데이터가 아직 없으므로 conflict
        없음이 정상이다.
        """
        from backend.domain.samba.brand.legacy_conflict import check_legacy_conflict

        cm, session = await _get_session_or_skip()
        try:
            conflict = await check_legacy_conflict(session, "ARC`TERYX")
            assert conflict is None
        finally:
            await cm.__aexit__(None, None, None)


class TestEvidenceCountIsLiveNotCached:
    @pytest.mark.asyncio
    async def test_count_reflects_actual_case_rows_no_manual_column(self) -> None:
        from backend.domain.samba.brand.model import SambaBrandRestriction
        from backend.domain.samba.brand.risk_case_model import SambaBrandRiskCase
        from backend.domain.samba.brand.risk_repository import (
            SambaBrandRiskCaseRepository,
        )

        # evidence_count 라는 컬럼 자체가 모델에 없어야 한다(수동 캐시 금지 원칙)
        assert not hasattr(SambaBrandRestriction, "evidence_count")

        cm, session = await _get_session_or_skip()
        try:
            brand = "__TEST_EVIDENCE_COUNT_BRAND__"
            repo = SambaBrandRiskCaseRepository(session)
            assert await repo.count_by_normalized_brand(brand) == 0

            for i in range(3):
                session.add(
                    SambaBrandRiskCase(
                        brand=brand,
                        normalized_brand=brand,
                        report_type="지재권",
                        confidence="B",
                        incident_date=date(2026, 8, 1 + i),
                    )
                )
            await session.flush()

            assert await repo.count_by_normalized_brand(brand) == 3
        finally:
            await cm.__aexit__(None, None, None)
