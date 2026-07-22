"""브랜드 판매 제한 판정 — 업로드 가드의 두뇌.

판정 순서 (먼저 걸리는 쪽이 이긴다):
  1. DB 목록 (`samba_brand_restriction`) — 사람이 확인한 결과. 엑셀·마켓 공지·본사 메일.
  2. 쿠팡 브랜드 API (`isUIDRequired`) — 목록에 없는 브랜드를 자동 판별.
  3. 둘 다 결론이 없으면 `unknown` → **차단**(안전 우선).

3번이 차단인 이유: 주 계정 A01260849 는 판매정지 이력이 있는 계정이다.
모르는 브랜드를 올렸다가 소명 대상이면 계정이 날아간다. 반대로 팔 수 있는
브랜드를 못 판 손해는 나중에 목록에 추가하면 복구된다. 손실이 비대칭이다.

API 로 새로 판별한 결과는 DB 에 기록한다 — 소명 브랜드는 마켓이 계속 추가하므로
"언제 무엇을 어떻게 판정했는지"가 남아야 다음에 검증할 수 있다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.samba.brand.model import (
    VERDICT_ALLOWED,
    VERDICT_BLOCKED,
    VERDICT_UNKNOWN,
    SambaBrandRestriction,
    normalize_brand,
)
from backend.utils.logger import logger


class BrandGuardResult:
    """판정 결과."""

    def __init__(
        self,
        verdict: str,
        reason: str,
        brand: str = "",
        source: str = "",
    ) -> None:
        self.verdict = verdict
        self.reason = reason
        self.brand = brand
        self.source = source

    @property
    def blocked(self) -> bool:
        """업로드를 막아야 하는가. unknown 도 막는다(안전 우선)."""
        return self.verdict != VERDICT_ALLOWED

    def __repr__(self) -> str:
        return f"<BrandGuard {self.brand!r} {self.verdict} ({self.reason})>"


class BrandGuardService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # 인스턴스 수명 인덱스 — 업로드 1건마다 새로 만들어도 152행 수준이라 가볍다.
    _index: Optional[dict[str, SambaBrandRestriction]] = None
    _blocked_keys: Optional[list[str]] = None

    async def _load_index(
        self, tenant_id: Optional[str]
    ) -> tuple[dict[str, SambaBrandRestriction], list[str]]:
        """브랜드 조회 인덱스 — 표기 변형(한↔영)까지 펼쳐서 담는다.

        엑셀은 '휠라'로 등재돼 있는데 수집 데이터는 'FILA'로 들어온다.
        정확일치만 보면 목록을 그대로 우회하므로(실측: FILA 가 차단을 빠져나가
        쿠팡 API 의 isUIDRequired=false 를 믿고 허용됨) 별칭을 함께 색인한다.
        """
        if self._index is not None and self._blocked_keys is not None:
            return self._index, self._blocked_keys

        # 전역 목록(tenant_id IS NULL) + 해당 테넌트 목록을 함께 본다.
        # 브랜드 소명 여부는 **어느 계정으로 팔든 동일**하므로 엑셀 목록은 전역으로
        # 적재된다. 테넌트 지정 행은 그 위에 얹는 예외로 취급한다.
        # (이 합집합을 빼먹으면 계정 tenant 로만 조회돼 전역 엑셀 목록이 통째로
        #  안 보인다 — 실측으로 휠라·라코스테가 전부 통과했다.)
        stmt = select(SambaBrandRestriction)
        if tenant_id is not None:
            stmt = stmt.where(
                (SambaBrandRestriction.tenant_id == tenant_id)
                | (SambaBrandRestriction.tenant_id.is_(None))
            )
        rows = list((await self.session.execute(stmt)).scalars().all())
        # 전역 → 테넌트 순으로 처리해 테넌트 예외가 나중에 덮어쓰게 한다
        rows.sort(key=lambda r: (r.tenant_id is not None,))

        index: dict[str, SambaBrandRestriction] = {}
        blocked: list[str] = []
        for row in rows:
            keys = {row.brand_key}
            # 한글 등재명 → 영문 표기 별칭 (brand_en 은 한→영 매핑)
            try:
                from backend.domain.samba.policy.brand_en import brand_en

                alt = normalize_brand(brand_en(row.brand) or "")
                if alt:
                    keys.add(alt)
            except Exception:
                pass
            for k in keys:
                # 사람이 확인한 판정(excel/manual)이 API 자동 판정을 이긴다.
                # 단, 판정이 서 있는 API 행은 판정이 빈(unknown) 사람 행보다 낫다.
                cur = index.get(k)
                if cur is None:
                    index[k] = row
                    continue
                cur_human = cur.source != "coupang_api"
                row_human = row.source != "coupang_api"
                cur_rank = (cur.verdict != VERDICT_UNKNOWN, cur_human)
                row_rank = (row.verdict != VERDICT_UNKNOWN, row_human)
                if row_rank > cur_rank:
                    index[k] = row
            if row.verdict == VERDICT_BLOCKED:
                blocked.extend(k for k in keys if len(k) >= 2)

        self._index = index
        self._blocked_keys = sorted(set(blocked), key=len, reverse=True)
        return index, self._blocked_keys

    async def _find(
        self, brand_key: str, tenant_id: Optional[str]
    ) -> Optional[SambaBrandRestriction]:
        index, _ = await self._load_index(tenant_id)
        return index.get(brand_key)

    async def _blocked_prefix(
        self, brand_key: str, tenant_id: Optional[str]
    ) -> Optional[str]:
        """차단 브랜드의 하위 표기인지 검사 → 걸린 차단 브랜드 키 반환.

        '아디다스오리지널스'·'헤지스골프'·'휠라언더웨어' 처럼 차단 브랜드명으로
        시작하는 이름은 같은 브랜드의 라인업이다. 쿠팡 API 는 이들을 별개
        브랜드로 보고 isUIDRequired=false 를 주지만(실측), 본사 지재권은 그대로
        걸린다. 접두 일치만 본다 — 중간 포함까지 보면 무관한 브랜드가 엮인다.
        """
        _, blocked_keys = await self._load_index(tenant_id)
        for bk in blocked_keys:
            if brand_key != bk and brand_key.startswith(bk):
                return bk
        return None

    async def check(
        self,
        brand: str,
        *,
        coupang_client: Any = None,
        tenant_id: Optional[str] = None,
        record: bool = True,
    ) -> BrandGuardResult:
        """브랜드 하나를 판정.

        coupang_client: CoupangClient. 주면 DB 에 없는 브랜드를 API 로 판별한다.
            없으면 DB 만 보고 판정하므로 미등록 브랜드는 전부 unknown(차단)이 된다.
        record: API 로 새로 판별한 결과를 DB 에 기록할지. 기본 True.
        """
        raw = (brand or "").strip()
        key = normalize_brand(raw)
        if not key:
            # 브랜드가 비었으면 판단 근거가 없다. 노브랜드 상품일 수도 있으나
            # 소명 대상인지 확인할 방법이 없으므로 통과시키지 않는다.
            return BrandGuardResult(VERDICT_UNKNOWN, "브랜드명 없음", raw, "none")

        row = await self._find(key, tenant_id)

        def _row_result(r: SambaBrandRestriction) -> BrandGuardResult:
            detail = r.ipr or r.soomyeong or ""
            reason = f"목록 등재({detail})" if detail else "목록 등재"
            if r.note:
                reason += f" · {r.note}"
            if normalize_brand(r.brand) != key:
                reason += f" · '{r.brand}' 표기변형"
            return BrandGuardResult(r.verdict, reason, raw, r.source)

        # 1) 사람이 확인한 판정이 최우선 (표기 변형 포함).
        #    쿠팡 API 가 뭐라 하든 이게 이긴다 — API 는 FILA·룰루레몬에
        #    isUIDRequired=false 를 주지만 실제로는 지재권 신고가 들어온 브랜드다.
        if (
            row is not None
            and row.source != "coupang_api"
            and row.verdict != VERDICT_UNKNOWN
        ):
            return _row_result(row)

        # 2) 차단 브랜드의 하위 라인업인가
        #    (아디다스오리지널스·헤지스골프·휠라언더웨어…)
        #    ※ API 자동 판정보다 **먼저** 본다. 하위 라인업은 쿠팡 라이브러리에
        #      별개 브랜드로 올라가 있어 isUIDRequired=false 가 나오지만,
        #      본사 지재권은 모브랜드 기준으로 걸린다.
        parent = await self._blocked_prefix(key, tenant_id)
        if parent:
            return BrandGuardResult(
                VERDICT_BLOCKED,
                f"차단 브랜드 '{parent}' 하위 표기",
                raw,
                "prefix",
            )

        # 3) 이전에 API 로 판별해 둔 결과 재사용
        if row is not None and row.verdict != VERDICT_UNKNOWN:
            return _row_result(row)

        # 4) 쿠팡 API 자동 판별
        if coupang_client is None:
            return BrandGuardResult(
                VERDICT_UNKNOWN, "목록에 없고 API 조회 불가", raw, "none"
            )

        try:
            info = await coupang_client.search_brand_info(raw)
        except Exception as e:
            logger.warning(f"[브랜드가드] '{raw}' API 조회 실패 — 차단 처리: {e}")
            return BrandGuardResult(VERDICT_UNKNOWN, f"API 조회 실패: {e}", raw, "none")

        matched = bool(info.get("matched"))
        uid = info.get("uid_required")

        if not matched:
            verdict, reason = (
                VERDICT_UNKNOWN,
                "쿠팡 브랜드 라이브러리에 정확일치 없음",
            )
        elif uid is True:
            verdict, reason = VERDICT_BLOCKED, "쿠팡 소명 대상(isUIDRequired=true)"
        elif uid is False:
            verdict, reason = VERDICT_ALLOWED, "쿠팡 자유판매(isUIDRequired=false)"
        else:
            verdict, reason = VERDICT_UNKNOWN, "isUIDRequired 값 없음"

        if record:
            await self._record_api_result(
                raw, key, verdict, matched, uid, tenant_id, existing=row
            )

        return BrandGuardResult(verdict, reason, raw, "coupang_api")

    async def _record_api_result(
        self,
        brand: str,
        key: str,
        verdict: str,
        matched: bool,
        uid: Optional[bool],
        tenant_id: Optional[str],
        existing: Optional[SambaBrandRestriction],
    ) -> None:
        """API 판별 결과를 DB 에 남긴다.

        사람이 **내린 판정**(blocked/allowed)은 덮어쓰지 않는다 — API 캐시 필드만
        갱신한다. 엑셀 '비소명' vs 쿠팡 API '소명' 불일치는 그 자체가 확인 대상이다.

        다만 엑셀에 이름만 있고 소명/지재권 칸이 비어 판정이 `unknown` 인 행은
        '사람이 아직 안 본 것'이지 '위험하다'가 아니다. 그런 빈칸은 API 결과로
        채운다 — 안 그러면 폴햄처럼 API 가 자유판매라고 확인해 준 브랜드가
        영영 차단된 채로 남는다.
        """
        now = datetime.now(tz=timezone.utc)
        try:
            if existing is not None:
                existing.coupang_uid_required = uid
                existing.coupang_matched = matched
                existing.coupang_checked_at = now
                if (
                    existing.source == "coupang_api"
                    or existing.verdict == VERDICT_UNKNOWN
                ):
                    existing.verdict = verdict
                existing.updated_at = now
                self.session.add(existing)
            else:
                self.session.add(
                    SambaBrandRestriction(
                        tenant_id=tenant_id,
                        brand=brand,
                        brand_key=key,
                        verdict=verdict,
                        coupang_uid_required=uid,
                        coupang_matched=matched,
                        coupang_checked_at=now,
                        source="coupang_api",
                        source_detail={"auto": True},
                        created_at=now,
                        updated_at=now,
                    )
                )
            await self.session.commit()
        except Exception as e:
            # 기록 실패가 업로드 판정을 막아서는 안 된다 — 판정은 이미 났다.
            logger.warning(f"[브랜드가드] '{brand}' 판정 기록 실패(무시): {e}")
            try:
                await self.session.rollback()
            except Exception:
                pass
