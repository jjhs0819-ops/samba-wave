"""SambaWave Tetris 정책 배치 service — board 조회 + shipment 트리거."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.samba.account.model import SambaMarketAccount
from backend.domain.samba.policy.model import SambaPolicy
from backend.domain.samba.shipment.repository import SambaShipmentRepository
from backend.domain.samba.shipment.service import SambaShipmentService
from backend.domain.samba.tetris.model import SambaTetrisAssignment
from backend.domain.samba.tetris.repository import SambaTetrisRepository
from backend.utils.logger import logger
from sqlalchemy import or_
from sqlmodel import select

# get_board() 인메모리 캐시 — 5분 TTL (61초짜리 쿼리, 자주 갱신 불필요)
_BOARD_CACHE_TTL = 300.0
_board_cache: dict = {}
_board_cache_lock = asyncio.Lock()

# 마켓타입 → 표시명 매핑 (account.market_type 기준)
_MARKET_DISPLAY_NAMES: dict[str, str] = {
    "smartstore": "스마트스토어",
    "coupang": "쿠팡",
    "ssg": "신세계몰",
    "11st": "11번가",
    "gmarket": "지마켓",
    "auction": "옥션",
    "gsshop": "GS샵",
    "lotteon": "롯데ON",
    "lottehome": "롯데홈쇼핑",
    "homeand": "홈앤쇼핑",
    "hmall": "HMALL",
    "kream": "KREAM",
    "playauto": "플레이오토",
}

# 레거시(배치 없이 등록된) 브랜드 기본 색상
_LEGACY_COLOR = "#6B7280"


def _norm_tetris_key(value: str | None) -> str:
    return "".join((value or "").split()).casefold()


def _norm_site_key(value: str | None) -> str:
    key = _norm_tetris_key(value)
    site_aliases = {
        "gsshop": "gsshop",
        "abcmart": "abcmart",
        "grandstage": "abcmart",
        "lotteon": "lotteon",
        "musinsa": "musinsa",
        "ssg": "ssg",
    }
    return site_aliases.get(key, key)


class SambaTetrisService:
    """테트리스 정책 배치 서비스."""

    def __init__(
        self,
        repo: SambaTetrisRepository,
        session: AsyncSession,
    ) -> None:
        self._repo = repo
        self._session = session

    # ──────────────────────────────────────────────
    # 내부 헬퍼
    # ──────────────────────────────────────────────

    def _make_ship_svc(self) -> SambaShipmentService:
        """Shipment 서비스 인스턴스 생성 (write session 공유)."""
        return SambaShipmentService(
            SambaShipmentRepository(self._session),
            self._session,
        )

    async def _get_product_ids_for_assign(
        self,
        tenant_id: Optional[str],
        source_site: str,
        brand_name: str,
        market_account_id: str,
    ) -> list[str]:
        """해당 브랜드 상품 중 해당 계정에 미등록된 상품 ID 목록 반환."""
        rows = await self._session.execute(
            text("""
                SELECT id FROM samba_collected_product
                WHERE (tenant_id IS NULL AND :tid_is_null OR tenant_id = :tid)
                  AND source_site = :site
                  AND BTRIM(brand) = :brand
                  AND (
                    registered_accounts IS NULL
                    OR NOT (registered_accounts::jsonb ? :account_id)
                  )
            """),
            {
                "tid": tenant_id,
                "tid_is_null": tenant_id is None,
                "site": source_site,
                "brand": brand_name,
                "account_id": market_account_id,
            },
        )
        return [row[0] for row in rows]

    async def _get_product_ids_for_remove(
        self,
        tenant_id: Optional[str],
        source_site: str,
        brand_name: str,
        market_account_id: str,
    ) -> list[str]:
        """해당 브랜드 상품 중 해당 계정에 등록된 상품 ID 목록 반환."""
        try:
            rows = await self._session.execute(
                text("""
                    SELECT id FROM samba_collected_product
                    WHERE (tenant_id IS NULL AND :tid_is_null OR tenant_id = :tid)
                      AND source_site = :site
                      AND BTRIM(brand) = :brand
                      AND registered_accounts IS NOT NULL
                      AND (registered_accounts::text LIKE :account_id OR registered_accounts::text ILIKE :account_id)
                """),
                {
                    "tid": tenant_id,
                    "tid_is_null": tenant_id is None,
                    "site": source_site,
                    "brand": brand_name,
                    "account_id": f"%{market_account_id}%",
                },
            )
            return [row[0] for row in rows]
        except Exception as e:
            logger.error(f"[테트리스] _get_product_ids_for_remove 쿼리 실패: {e}")
            return []

    # ──────────────────────────────────────────────
    # 보드 조회
    # ──────────────────────────────────────────────

    async def get_board(self, tenant_id: Optional[str]) -> dict[str, Any]:
        """
        테트리스 보드 전체 구조 반환.

        구조:
        {
          "markets": [{ market_type, market_name, accounts: [...] }],
          "unassigned": [{ source_site, brand_name, collected_count }]
        }
        """
        import time as _time

        cache_key = str(tenant_id)
        now_ts = _time.monotonic()
        cached = _board_cache.get(cache_key)
        if cached is not None and (now_ts - cached["ts"]) < _BOARD_CACHE_TTL:
            return cached["data"]

        async with _board_cache_lock:
            cached = _board_cache.get(cache_key)
            if (
                cached is not None
                and (_time.monotonic() - cached["ts"]) < _BOARD_CACHE_TTL
            ):
                return cached["data"]

            result = await self._get_board_uncached(tenant_id)
            _board_cache[cache_key] = {"data": result, "ts": _time.monotonic()}
            return result

    async def _get_board_uncached(self, tenant_id: Optional[str]) -> dict[str, Any]:
        # 1. 마켓 계정 전체 로드
        acc_stmt = select(SambaMarketAccount)
        if tenant_id is not None:
            # Account APIs expose both tenant-scoped accounts and pre-tenant legacy
            # accounts with NULL tenant_id. Keep Tetris aligned with that behavior.
            acc_stmt = acc_stmt.where(
                or_(
                    SambaMarketAccount.tenant_id == tenant_id,
                    SambaMarketAccount.tenant_id == None,  # noqa: E711
                )
            )
        else:
            acc_stmt = acc_stmt.where(SambaMarketAccount.tenant_id == None)  # noqa: E711
        acc_result = await self._session.execute(acc_stmt)
        accounts: list[SambaMarketAccount] = list(acc_result.scalars().all())

        # 2. 테트리스 배치 전체 로드
        assignments: list[SambaTetrisAssignment] = await self._repo.list_by_tenant(
            tenant_id
        )

        # 3. 정책 전체 로드 → id: (name, color) 딕셔너리
        # 계정 쿼리와 동일하게 테넌트 정책 + 레거시(NULL) 정책 모두 포함
        if tenant_id is not None:
            pol_stmt = select(SambaPolicy).where(
                or_(
                    SambaPolicy.tenant_id == tenant_id,
                    SambaPolicy.tenant_id == None,  # noqa: E711
                )
            )
        else:
            pol_stmt = select(SambaPolicy).where(SambaPolicy.tenant_id == None)  # noqa: E711
        pol_result = await self._session.execute(pol_stmt)
        policies: list[SambaPolicy] = list(pol_result.scalars().all())
        policy_map: dict[str, tuple[str, str]] = {}
        for pol in policies:
            extras = pol.extras or {}
            color = (
                extras.get("color", "#3B82F6")
                if isinstance(extras, dict)
                else "#3B82F6"
            )
            policy_map[pol.id] = (pol.name, color)

        # 3.5. 소싱그룹(검색그룹) applied_policy_id 로드
        # tetris assignment가 없는 브랜드도 소싱그룹 정책 색상으로 표시
        sf_rows = await self._session.execute(
            text("""
                SELECT DISTINCT ON (source_site, source_brand_name)
                    source_site, source_brand_name, applied_policy_id
                FROM samba_search_filter
                WHERE applied_policy_id IS NOT NULL
                  AND source_brand_name IS NOT NULL
                  AND source_brand_name != ''
                  AND (tenant_id IS NULL AND :tid_is_null OR tenant_id = :tid)
                ORDER BY source_site, source_brand_name, updated_at DESC
            """),
            {"tid": tenant_id, "tid_is_null": tenant_id is None},
        )
        # (norm_site, norm_brand) → (policy_id, policy_name, policy_color)
        sf_policy_map: dict[tuple[str, str], tuple[str, str, str]] = {}
        for row in sf_rows:
            site, brand, pid = row[0], row[1], row[2]
            if not brand or not pid or pid not in policy_map:
                continue
            nkey = (_norm_site_key(site), _norm_tetris_key(brand))
            if nkey not in sf_policy_map:
                pol_name, pol_color = policy_map[pid]
                sf_policy_map[nkey] = (pid, pol_name, pol_color)

        # 4. Raw SQL 집계 — 소싱처·브랜드별 수집 수 (상품수집 페이지와 동일 기준: cp.brand만)
        collected_rows = await self._session.execute(
            text("""
                SELECT
                    source_site,
                    BTRIM(brand) AS effective_brand,
                    COUNT(*) AS cnt,
                    COUNT(*) FILTER (
                        WHERE COALESCE(cast(tags AS text), '') LIKE '%__ai_tagged__%'
                    ) AS ai_tagged_cnt
                FROM samba_collected_product
                WHERE (tenant_id IS NULL AND :tid_is_null OR tenant_id = :tid)
                  AND source_site IS NOT NULL
                  AND brand IS NOT NULL
                  AND BTRIM(brand) != ''
                GROUP BY source_site, BTRIM(brand)
            """),
            {"tid": tenant_id, "tid_is_null": tenant_id is None},
        )
        # collected_map[(source_site, trimmed_brand)] = count
        collected_map: dict[tuple[str, str], int] = {}
        ai_tagged_map: dict[tuple[str, str], int] = {}
        collected_label_map: dict[tuple[str, str], tuple[str, str]] = {}
        normalized_collected_map: dict[tuple[str, str], int] = {}
        normalized_ai_tagged_map: dict[tuple[str, str], int] = {}
        normalized_label_map: dict[tuple[str, str], tuple[str, str]] = {}
        for row in collected_rows:
            site = row[0]
            brand = row[1]
            if not brand:
                continue
            key = (site, brand)
            norm_key = (_norm_site_key(site), _norm_tetris_key(brand))
            collected_map[key] = collected_map.get(key, 0) + int(row[2] or 0)
            ai_tagged_map[key] = ai_tagged_map.get(key, 0) + int(row[3] or 0)
            collected_label_map.setdefault(key, (site, brand))
            normalized_collected_map[norm_key] = normalized_collected_map.get(
                norm_key, 0
            ) + int(row[2] or 0)
            normalized_ai_tagged_map[norm_key] = normalized_ai_tagged_map.get(
                norm_key, 0
            ) + int(row[3] or 0)
            normalized_label_map.setdefault(norm_key, (site, brand))

        logger.info(
            f"[테트리스] collected_map={len(collected_map)}, "
            f"accounts={len(accounts)}, tenant_id={tenant_id}"
        )

        # 5. Raw SQL 집계 — JSONB 함수로 account_id 전개 후 DB에서 집계 (cp.brand만)
        registered_rows = await self._session.execute(
            text("""
                SELECT
                    source_site,
                    BTRIM(brand) AS effective_brand,
                    jsonb_array_elements_text(registered_accounts) AS account_id,
                    COUNT(*) AS cnt
                FROM samba_collected_product
                WHERE (tenant_id IS NULL AND :tid_is_null OR tenant_id = :tid)
                  AND is_unregistered = FALSE
                  AND registered_accounts IS NOT NULL
                  AND jsonb_typeof(registered_accounts) = 'array'
                  AND jsonb_array_length(registered_accounts) > 0
                  AND source_site IS NOT NULL
                  AND brand IS NOT NULL
                  AND BTRIM(brand) != ''
                GROUP BY source_site, BTRIM(brand), account_id
            """),
            {"tid": tenant_id, "tid_is_null": tenant_id is None},
        )
        # registered_map[(source_site, trimmed_brand, account_id)] = count
        registered_map: dict[tuple[str, str, str], int] = {}
        normalized_registered_map: dict[tuple[str, str, str], int] = {}
        for row in registered_rows:
            site = row[0]
            brand = row[1]
            account_id = row[2]
            if not brand or not account_id:
                continue
            key = (site, brand, account_id)
            norm_key = (_norm_site_key(site), _norm_tetris_key(brand), account_id)
            registered_map[key] = registered_map.get(key, 0) + int(row[3] or 0)
            normalized_registered_map[norm_key] = normalized_registered_map.get(
                norm_key, 0
            ) + int(row[3] or 0)

        logger.info(
            f"[테트리스] registered_map={len(registered_map)}, assignments={len(assignments)}"
        )

        # 6. 계정별 등록 총 수 집계
        # account_registered_total[account_id] = sum
        account_registered_total: dict[str, int] = {}
        for (_, _, acc_id), cnt in registered_map.items():
            account_registered_total[acc_id] = (
                account_registered_total.get(acc_id, 0) + cnt
            )

        # 7. 등록된 (site, brand, account_id) 집합 — 레거시 감지용
        registered_keys: set[tuple[str, str, str]] = set(
            normalized_registered_map.keys()
        )

        # 9. 보드 조립
        # O(n²) 방지: 계정별 assignment 사전 인덱싱
        assignments_by_account: dict[str, list[SambaTetrisAssignment]] = {}
        for a in assignments:
            assignments_by_account.setdefault(a.market_account_id, []).append(a)

        # O(n²) 방지: 계정별 registered legacy_keys 사전 인덱싱
        legacy_keys_by_account: dict[str, list[tuple[str, str]]] = {}
        for site, brand, aid in registered_keys:
            legacy_keys_by_account.setdefault(aid, []).append((site, brand))

        # market_type → market group dict
        market_groups: dict[str, dict[str, Any]] = {}
        market_order: list[str] = []

        for acc in accounts:
            mt = acc.market_type
            if mt not in market_groups:
                market_groups[mt] = {
                    "market_type": mt,
                    "market_name": acc.market_name or _MARKET_DISPLAY_NAMES.get(mt, mt),
                    "accounts": [],
                }
                market_order.append(mt)

            # max_count: additional_fields.maxCount
            add_fields: dict[str, Any] = (
                acc.additional_fields if isinstance(acc.additional_fields, dict) else {}
            ) or {}
            max_count: int = int(add_fields.get("maxCount", 0) or 0)
            account_order_raw = add_fields.get("tetrisAccountOrder")
            account_order = (
                int(account_order_raw)
                if isinstance(account_order_raw, (int, float, str))
                and str(account_order_raw).strip() != ""
                else None
            )

            # 해당 계정에 배치된 assignment 목록 — O(1) dict 조회
            acc_assignments: list[SambaTetrisAssignment] = sorted(
                assignments_by_account.get(acc.id, []),
                key=lambda a: a.position_order,
            )

            assignment_blocks: list[dict[str, Any]] = []
            for a in acc_assignments:
                if a.policy_id:
                    pol_name, pol_color = policy_map.get(
                        a.policy_id, ("기본정책", "#3B82F6")
                    )
                    eff_policy_id = a.policy_id
                else:
                    _nk = (
                        _norm_site_key(a.source_site),
                        _norm_tetris_key(a.brand_name),
                    )
                    _sf = sf_policy_map.get(_nk)
                    if _sf:
                        eff_policy_id, pol_name, pol_color = _sf
                    else:
                        eff_policy_id, pol_name, pol_color = (
                            None,
                            "기본정책",
                            "#3B82F6",
                        )
                exact_key = (a.source_site, a.brand_name)
                norm_key = (
                    _norm_site_key(a.source_site),
                    _norm_tetris_key(a.brand_name),
                )
                reg_cnt = registered_map.get((a.source_site, a.brand_name, acc.id), 0)
                if reg_cnt <= 0:
                    reg_cnt = normalized_registered_map.get((*norm_key, acc.id), 0)
                col_cnt = collected_map.get(exact_key, 0)
                ai_cnt = ai_tagged_map.get(exact_key, 0)
                display_site, display_brand = collected_label_map.get(
                    exact_key, (a.source_site, a.brand_name)
                )
                if col_cnt <= 0:
                    col_cnt = normalized_collected_map.get(norm_key, 0)
                    ai_cnt = normalized_ai_tagged_map.get(norm_key, 0)
                    display_site, display_brand = normalized_label_map.get(
                        norm_key, (a.source_site, a.brand_name)
                    )
                if col_cnt <= 0 and reg_cnt <= 0:
                    continue
                assignment_blocks.append(
                    {
                        "id": a.id,
                        "source_site": display_site,
                        "brand_name": display_brand,
                        "policy_id": eff_policy_id,
                        "policy_name": pol_name,
                        "policy_color": pol_color,
                        "registered_count": reg_cnt,
                        "collected_count": col_cnt,
                        "ai_tagged_count": ai_cnt,
                        "position_order": a.position_order,
                        "is_legacy": False,
                    }
                )

            # 레거시: registered_map에 있지만 tetris 배치 없는 브랜드
            assigned_site_brand = {
                (_norm_site_key(a.source_site), _norm_tetris_key(a.brand_name))
                for a in acc_assignments
            }
            # O(1) dict 조회 — registered_keys 전체 순회 불필요
            legacy_keys = [
                (site, brand)
                for (site, brand) in legacy_keys_by_account.get(acc.id, [])
                if (site, brand) not in assigned_site_brand
            ]
            _fallback_color = next((v[1] for v in policy_map.values()), _LEGACY_COLOR)
            for site, brand in legacy_keys:
                reg_cnt = normalized_registered_map.get((site, brand, acc.id), 0)
                col_cnt = normalized_collected_map.get((site, brand), 0)
                ai_cnt = normalized_ai_tagged_map.get((site, brand), 0)
                if col_cnt <= 0 and ai_cnt <= 0:
                    continue
                orig_site, orig_brand = normalized_label_map.get(
                    (site, brand), (site, brand)
                )
                _sf_leg = sf_policy_map.get((site, brand))
                assignment_blocks.append(
                    {
                        "id": None,
                        "source_site": orig_site,
                        "brand_name": orig_brand,
                        "policy_id": _sf_leg[0] if _sf_leg else None,
                        "policy_name": _sf_leg[1] if _sf_leg else None,
                        "policy_color": _sf_leg[2] if _sf_leg else _fallback_color,
                        "registered_count": reg_cnt,
                        "collected_count": col_cnt,
                        "ai_tagged_count": ai_cnt,
                        "position_order": 9999,
                        "is_legacy": True,
                    }
                )
            # 계정 총 수집 수 (배치된 브랜드 기준)
            total_collected = sum(b["collected_count"] for b in assignment_blocks)
            total_registered = account_registered_total.get(acc.id, 0)

            market_groups[mt]["accounts"].append(
                {
                    "account_id": acc.id,
                    "account_label": acc.account_label,
                    "account_order": account_order,
                    "max_count": max_count,
                    "total_registered": total_registered,
                    "total_collected": total_collected,
                    "assignments": assignment_blocks,
                }
            )

        # 10. unassigned: 수집 상품이 있는 모든 브랜드 표시 (다중 계정 중복 배치 허용)
        # 이미 일부 계정에 배치된 브랜드도 다른 계정에 추가 배치 가능하도록 풀에 항상 포함
        unassigned: list[dict[str, Any]] = []
        registered_total_by_brand: dict[tuple[str, str], int] = {}
        for (site, brand, _), cnt in registered_map.items():
            key = (site, brand)
            registered_total_by_brand[key] = registered_total_by_brand.get(key, 0) + cnt

        for (site, brand), cnt in collected_map.items():
            if cnt > 0:
                unassigned.append(
                    {
                        "source_site": collected_label_map.get(
                            (site, brand), (site, brand)
                        )[0],
                        "brand_name": collected_label_map.get(
                            (site, brand), (site, brand)
                        )[1],
                        "registered_count": registered_total_by_brand.get(
                            (site, brand), 0
                        ),
                        "collected_count": cnt,
                        "ai_tagged_count": ai_tagged_map.get((site, brand), 0),
                    }
                )

        if unassigned:
            logger.info(f"[테트리스] unassigned 샘플: {unassigned[:3]}")

        return {
            "markets": [market_groups[mt] for mt in market_order],
            "unassigned": unassigned,
        }

    # ──────────────────────────────────────────────
    # 배치 저장
    # ──────────────────────────────────────────────

    async def assign(
        self,
        tenant_id: Optional[str],
        source_site: str,
        brand_name: str,
        market_account_id: str,
        policy_id: Optional[str],
        position_order: int,
    ) -> SambaTetrisAssignment:
        """배치 저장 후 해당 브랜드 미등록 상품 전송 트리거."""
        # 동일 계정에 동일 브랜드 중복 배치 방지 (다른 계정에는 허용)
        existing = await self._repo.find_existing(
            tenant_id, source_site, brand_name, market_account_id
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"{source_site}/{brand_name} 배치가 이미 해당 계정에 존재합니다 (id={existing.id})",
            )

        assignment = await self._repo.create_async(
            tenant_id=tenant_id,
            source_site=source_site,
            brand_name=brand_name,
            market_account_id=market_account_id,
            policy_id=policy_id,
            position_order=position_order,
        )

        # 즉시 전송하지 않음 — 인터벌 루프(sync_all)에서 잡큐로 스테이징
        logger.info(
            f"[테트리스] assign 저장 완료 — {source_site}/{brand_name} "
            f"→ {market_account_id} (인터벌 루프에서 등록 예정)"
        )

        return assignment

    # ──────────────────────────────────────────────
    # 배치 삭제
    # ──────────────────────────────────────────────

    async def remove(
        self,
        assignment_id: str,
        tenant_id: Optional[str],
    ) -> bool:
        """배치 삭제 후 해당 계정 상품 마켓 삭제 트리거."""
        assignment = await self._repo.get_async(assignment_id)
        if not assignment:
            return False
        # 테넌트 권한 검증
        if assignment.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="권한이 없습니다")

        source_site = assignment.source_site
        brand_name = assignment.brand_name
        market_account_id = assignment.market_account_id

        deleted = await self._repo.delete_async(assignment_id)

        # 등록된 상품 마켓 삭제 트리거 (백그라운드)
        product_ids = await self._get_product_ids_for_remove(
            tenant_id, source_site, brand_name, market_account_id
        )
        if product_ids:
            ship_svc = self._make_ship_svc()
            asyncio.create_task(
                ship_svc.delete_from_markets(
                    product_ids=product_ids,
                    target_account_ids=[market_account_id],
                )
            )
            logger.info(
                f"[테트리스] remove 마켓삭제 트리거 — {source_site}/{brand_name} "
                f"← {market_account_id} ({len(product_ids)}건)"
            )

        return deleted

    # ──────────────────────────────────────────────
    # 배치 이동
    # ──────────────────────────────────────────────

    async def move(
        self,
        assignment_id: str,
        tenant_id: Optional[str],
        new_account_id: str,
        policy_id: Optional[str],
        position_order: int,
    ) -> SambaTetrisAssignment:
        """다른 계정으로 이동 — 기존 계정 마켓삭제 → 신규 계정 전송."""
        assignment = await self._repo.get_async(assignment_id)
        if not assignment:
            raise HTTPException(status_code=404, detail="배치를 찾을 수 없습니다")
        if assignment.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="권한이 없습니다")

        old_account_id = assignment.market_account_id
        source_site = assignment.source_site
        brand_name = assignment.brand_name

        # 기존 계정 마켓삭제 트리거 (백그라운드)
        old_product_ids = await self._get_product_ids_for_remove(
            tenant_id, source_site, brand_name, old_account_id
        )
        if old_product_ids:
            ship_svc = self._make_ship_svc()
            asyncio.create_task(
                ship_svc.delete_from_markets(
                    product_ids=old_product_ids,
                    target_account_ids=[old_account_id],
                )
            )
            logger.info(
                f"[테트리스] move 마켓삭제 트리거 — {source_site}/{brand_name} "
                f"← {old_account_id} ({len(old_product_ids)}건)"
            )

        # 배치 업데이트
        updated = await self._repo.update_async(
            assignment_id,
            market_account_id=new_account_id,
            policy_id=policy_id,
            position_order=position_order,
            updated_at=datetime.now(tz=timezone.utc),
        )
        if not updated:
            raise HTTPException(status_code=404, detail="배치 업데이트 실패")

        # 신규 계정 전송 트리거 (백그라운드)
        new_product_ids = await self._get_product_ids_for_assign(
            tenant_id, source_site, brand_name, new_account_id
        )
        if new_product_ids:
            ship_svc = self._make_ship_svc()
            asyncio.create_task(
                ship_svc.start_update(
                    product_ids=new_product_ids,
                    update_items=["price", "stock", "image", "description"],
                    target_account_ids=[new_account_id],
                )
            )
            logger.info(
                f"[테트리스] move 전송 트리거 — {source_site}/{brand_name} "
                f"→ {new_account_id} ({len(new_product_ids)}건)"
            )

        return updated

    # ──────────────────────────────────────────────
    # 순서 변경
    # ──────────────────────────────────────────────

    async def reorder(
        self,
        assignment_id: str,
        tenant_id: Optional[str],
        position_order: int,
    ) -> SambaTetrisAssignment:
        """순서만 변경 (shipment 트리거 없음)."""
        assignment = await self._repo.get_async(assignment_id)
        if not assignment:
            raise HTTPException(status_code=404, detail="배치를 찾을 수 없습니다")
        if assignment.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="권한이 없습니다")

        updated = await self._repo.update_async(
            assignment_id,
            position_order=position_order,
            updated_at=datetime.now(tz=timezone.utc),
        )
        if not updated:
            raise HTTPException(status_code=404, detail="배치 업데이트 실패")

        return updated

    # ──────────────────────────────────────────────
    # 전체 sync (인터벌 자동등록 — A안: 미등록 보충)
    # ──────────────────────────────────────────────

    async def sync_all(self, tenant_id: Optional[str]) -> dict[str, int]:
        """현재 배치 전체 기준으로 미등록 상품 transmit 잡 생성 (브랜드×계정별 별도 잡)."""
        from backend.domain.samba.job.repository import SambaJobRepository

        assignments = await self._repo.list_by_tenant(tenant_id)

        job_repo = SambaJobRepository(self._session)
        job_count = 0
        total_products = 0

        # 브랜드×계정 조합별 별도 잡 — 계정이 같아도 브랜드마다 독립 잡으로 스테이징
        # (워커가 동일 계정 잡은 순차, 다른 계정 잡은 병렬로 자동 처리)
        for a in assignments:
            pids = await self._get_product_ids_for_assign(
                tenant_id, a.source_site, a.brand_name, a.market_account_id
            )
            if not pids:
                continue
            await job_repo.create_async(
                tenant_id=tenant_id,
                job_type="transmit",
                payload={
                    "product_ids": pids,
                    "update_items": ["price", "stock", "image", "description"],
                    "target_account_ids": [a.market_account_id],
                    "source_site": a.source_site,
                    "brand_name": a.brand_name,
                    "skip_unchanged": True,
                },
            )
            job_count += 1
            total_products += len(pids)

        logger.info(
            f"[테트리스 sync] {len(assignments)}개 배치 → "
            f"{job_count}개 잡, {total_products}개 상품"
        )
        return {
            "assignments": len(assignments),
            "jobs": job_count,
            "triggered": total_products,
        }
