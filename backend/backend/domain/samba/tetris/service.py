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
from sqlmodel import select


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
                WHERE tenant_id = :tid
                  AND source_site = :site
                  AND brand = :brand
                  AND (
                    registered_accounts IS NULL
                    OR NOT (registered_accounts::jsonb ? :account_id)
                  )
            """),
            {
                "tid": tenant_id,
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
                    WHERE tenant_id = :tid
                      AND source_site = :site
                      AND brand = :brand
                      AND registered_accounts IS NOT NULL
                      AND (registered_accounts::text LIKE :account_id OR registered_accounts::text ILIKE :account_id)
                """),
                {
                    "tid": tenant_id,
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
        # 1. 마켓 계정 전체 로드
        acc_stmt = select(SambaMarketAccount).where(
            SambaMarketAccount.tenant_id == tenant_id,
            SambaMarketAccount.is_active == True,  # noqa: E712
        )
        acc_result = await self._session.execute(acc_stmt)
        accounts: list[SambaMarketAccount] = list(acc_result.scalars().all())

        # 2. 테트리스 배치 전체 로드
        assignments: list[SambaTetrisAssignment] = await self._repo.list_by_tenant(
            tenant_id
        )

        # 3. 정책 전체 로드 → id: (name, color) 딕셔너리
        pol_stmt = select(SambaPolicy).where(SambaPolicy.tenant_id == tenant_id)
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

        # 4. Raw SQL 집계 — 소싱처·브랜드별 수집 수
        collected_rows = await self._session.execute(
            text("""
                SELECT source_site, brand, COUNT(*) AS cnt
                FROM samba_collected_product
                WHERE tenant_id = :tid
                  AND brand IS NOT NULL
                  AND source_site IS NOT NULL
                GROUP BY source_site, brand
            """),
            {"tid": tenant_id},
        )
        # collected_map[(source_site, brand)] = count
        collected_map: dict[tuple[str, str], int] = {
            (row[0], row[1]): row[2] for row in collected_rows
        }

        # 5. Raw SQL 집계 — JSONB 함수로 account_id 전개 후 DB에서 집계
        registered_rows = await self._session.execute(
            text("""
                SELECT source_site, brand,
                       jsonb_array_elements_text(registered_accounts::jsonb) AS account_id,
                       COUNT(*) AS cnt
                FROM samba_collected_product
                WHERE tenant_id = :tid
                  AND registered_accounts IS NOT NULL
                  AND registered_accounts::text NOT IN ('null', '[]', '')
                  AND brand IS NOT NULL
                  AND source_site IS NOT NULL
                GROUP BY source_site, brand, account_id
            """),
            {"tid": tenant_id},
        )
        # registered_map[(source_site, brand, account_id)] = count
        registered_map: dict[tuple[str, str, str], int] = {
            (row[0], row[1], row[2]): row[3] for row in registered_rows
        }

        # 6. 계정별 등록 총 수 집계
        # account_registered_total[account_id] = sum
        account_registered_total: dict[str, int] = {}
        for (_, _, acc_id), cnt in registered_map.items():
            account_registered_total[acc_id] = (
                account_registered_total.get(acc_id, 0) + cnt
            )

        # 7. 배치 인덱스: (source_site, brand_name) → assignment
        assignment_index: dict[tuple[str, str], SambaTetrisAssignment] = {
            (a.source_site, a.brand_name): a for a in assignments
        }

        # 8. 등록된 (site, brand, account_id) 집합 — 레거시 감지용
        registered_keys: set[tuple[str, str, str]] = set(registered_map.keys())

        # 9. 보드 조립
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

            # 해당 계정에 배치된 assignment 목록
            acc_assignments: list[SambaTetrisAssignment] = [
                a for a in assignments if a.market_account_id == acc.id
            ]
            # 배치 순서 정렬 (이미 repo에서 정렬됐지만 계정 필터 후 재정렬)
            acc_assignments.sort(key=lambda a: a.position_order)

            assignment_blocks: list[dict[str, Any]] = []
            for a in acc_assignments:
                pol_name, pol_color = (
                    policy_map.get(a.policy_id or "", ("기본정책", "#3B82F6"))
                    if a.policy_id
                    else ("기본정책", "#3B82F6")
                )
                reg_cnt = registered_map.get((a.source_site, a.brand_name, acc.id), 0)
                col_cnt = collected_map.get((a.source_site, a.brand_name), 0)
                assignment_blocks.append(
                    {
                        "id": a.id,
                        "source_site": a.source_site,
                        "brand_name": a.brand_name,
                        "policy_id": a.policy_id,
                        "policy_name": pol_name,
                        "policy_color": pol_color,
                        "registered_count": reg_cnt,
                        "collected_count": col_cnt,
                        "position_order": a.position_order,
                        "is_legacy": False,
                    }
                )

            # 레거시: registered_map에 있지만 tetris 배치 없는 브랜드
            assigned_site_brand = {
                (a.source_site, a.brand_name) for a in acc_assignments
            }
            legacy_keys = [
                (site, brand)
                for (site, brand, aid) in registered_keys
                if aid == acc.id and (site, brand) not in assigned_site_brand
            ]
            for site, brand in legacy_keys:
                reg_cnt = registered_map.get((site, brand, acc.id), 0)
                col_cnt = collected_map.get((site, brand), 0)
                assignment_blocks.append(
                    {
                        "id": None,
                        "source_site": site,
                        "brand_name": brand,
                        "policy_id": None,
                        "policy_name": None,
                        "policy_color": _LEGACY_COLOR,
                        "registered_count": reg_cnt,
                        "collected_count": col_cnt,
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
                    "max_count": max_count,
                    "total_registered": total_registered,
                    "total_collected": total_collected,
                    "assignments": assignment_blocks,
                }
            )

        # 10. unassigned: 수집은 있지만 어떤 계정에도 등록·배치 없는 브랜드
        all_registered_site_brand: set[tuple[str, str]] = {
            (site, brand) for (site, brand, _) in registered_keys
        }
        all_assigned_site_brand: set[tuple[str, str]] = {
            (a.source_site, a.brand_name) for a in assignments
        }
        already_placed = all_registered_site_brand | all_assigned_site_brand

        unassigned: list[dict[str, Any]] = []
        for (site, brand), cnt in collected_map.items():
            if (site, brand) not in already_placed and cnt > 0:
                unassigned.append(
                    {
                        "source_site": site,
                        "brand_name": brand,
                        "collected_count": cnt,
                    }
                )

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
        # 기존 배치 확인 (중복 방지)
        existing = await self._repo.find_existing(tenant_id, source_site, brand_name)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"{source_site}/{brand_name} 배치가 이미 존재합니다 (id={existing.id})",
            )

        assignment = await self._repo.create_async(
            tenant_id=tenant_id,
            source_site=source_site,
            brand_name=brand_name,
            market_account_id=market_account_id,
            policy_id=policy_id,
            position_order=position_order,
        )

        # 미등록 상품 전송 트리거 (백그라운드)
        product_ids = await self._get_product_ids_for_assign(
            tenant_id, source_site, brand_name, market_account_id
        )
        if product_ids:
            ship_svc = self._make_ship_svc()
            asyncio.create_task(
                ship_svc.start_update(
                    product_ids=product_ids,
                    update_items=["price", "stock", "image", "description"],
                    target_account_ids=[market_account_id],
                )
            )
            logger.info(
                f"[테트리스] assign 전송 트리거 — {source_site}/{brand_name} "
                f"→ {market_account_id} ({len(product_ids)}건)"
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
