from abc import ABC, abstractmethod
from typing import Any
import logging

logger = logging.getLogger(__name__)


class MarketPlugin(ABC):
    """마켓 플러그인 기본 클래스.
    새 마켓 추가 시 execute()와 transform() 2개만 구현.
    인증 로드, 정책 주입, 에러 분류는 base가 처리.
    """

    market_type: str  # "smartstore"
    policy_key: str  # "스마트스토어"
    required_fields: list[str] = ["name", "sale_price"]

    # ── 신규등록 원자 선점(claim) — 동시전송/타임아웃 시 중복 CREATE 차단 ──
    # market_product_nos[account]에 __claiming__<epoch> 표식을 원자 기록해 직렬화.
    # 쿠팡/롯데온은 자체 구현을 갖고, ESM(옥션/G마켓)은 이 base 버전을 사용한다.
    _CLAIM_PREFIX = "__claiming__"
    _CLAIM_STALE_SECONDS = 900

    async def _claim_registration_slot(
        self, product_id: str, account_id: str, claim_val: str
    ) -> tuple[str, str]:
        """등록 슬롯 원자 선점 — 동시 이중등록 차단 (쿠팡/롯데온 동일 패턴).

        반환 (status, value):
          owned   — 이 실행이 선점 성공(등록 진행). value=claim_val
          exists  — 이미 실제 마켓상품번호 매핑 존재. value=번호
          pending — 다른 실행이 등록 중(신선한 선점). value=상대 선점값
          stale   — 방치된 선점(비정상 종료 흔적). value=옛 선점값
        조회/선점 실패 시 ("owned", claim_val) — fail-open, 등록을 막지 않는다.
        """
        try:
            from sqlalchemy import text as _t
            from backend.db.orm import get_write_session as _gws

            async with _gws() as _s:
                _r = await _s.execute(
                    _t(
                        "UPDATE samba_collected_product "
                        "SET market_product_nos = jsonb_set("
                        "  CASE WHEN market_product_nos IS NOT NULL "
                        "        AND jsonb_typeof(market_product_nos) = 'object' "
                        "       THEN market_product_nos ELSE '{}'::jsonb END, "
                        "  ARRAY[:acct]::text[], to_jsonb(CAST(:val AS text)), true) "
                        "WHERE id = :pid AND (market_product_nos IS NULL "
                        "  OR jsonb_typeof(market_product_nos) <> 'object' "
                        "  OR NOT jsonb_exists(market_product_nos, :acct)) "
                        "RETURNING id"
                    ),
                    {"pid": product_id, "acct": account_id, "val": claim_val},
                )
                _won = _r.first() is not None
                _v = None
                if not _won:
                    _v = (
                        await _s.execute(
                            _t(
                                "SELECT market_product_nos ->> :acct "
                                "FROM samba_collected_product WHERE id = :pid"
                            ),
                            {"pid": product_id, "acct": account_id},
                        )
                    ).scalar()
                await _s.commit()
            if _won:
                return ("owned", claim_val)
            _vs = str(_v or "").strip()
            if not _vs:
                return ("owned", claim_val)
            if _vs.startswith(self._CLAIM_PREFIX):
                import time as _tm

                try:
                    _ts = int(_vs[len(self._CLAIM_PREFIX) :])
                except Exception:
                    _ts = 0
                if _tm.time() - _ts > self._CLAIM_STALE_SECONDS:
                    return ("stale", _vs)
                return ("pending", _vs)
            if _vs.startswith("{"):
                return ("owned", claim_val)
            return ("exists", _vs)
        except Exception as _e:
            logger.warning(
                f"[{self.market_type}] 등록 선점 조회 실패(무시, 등록 진행): {_e}"
            )
            return ("owned", claim_val)

    async def _cas_claim(
        self, product_id: str, account_id: str, old_val: str, new_val: str
    ) -> bool:
        """방치된 선점값 원자 교체(compare-and-swap). 성공 시 True."""
        try:
            from sqlalchemy import text as _t
            from backend.db.orm import get_write_session as _gws

            async with _gws() as _s:
                _r = await _s.execute(
                    _t(
                        "UPDATE samba_collected_product "
                        "SET market_product_nos = jsonb_set(market_product_nos, "
                        "  ARRAY[:acct]::text[], to_jsonb(CAST(:val AS text)), true) "
                        "WHERE id = :pid AND market_product_nos ->> :acct = :old "
                        "RETURNING id"
                    ),
                    {
                        "pid": product_id,
                        "acct": account_id,
                        "val": new_val,
                        "old": old_val,
                    },
                )
                _won = _r.first() is not None
                await _s.commit()
            return _won
        except Exception as _e:
            logger.warning(f"[{self.market_type}] 선점 교체 실패(무시): {_e}")
            return False

    async def _release_registration_claim(
        self, product_id: str, account_id: str, claim_val: str
    ) -> None:
        """등록 실패 시 선점 표식 제거 — 아직 내 선점값일 때만(CAS)."""
        if not (product_id and account_id):
            return
        try:
            from sqlalchemy import text as _t
            from backend.db.orm import get_write_session as _gws

            async with _gws() as _s:
                await _s.execute(
                    _t(
                        "UPDATE samba_collected_product "
                        "SET market_product_nos = market_product_nos - :acct "
                        "WHERE id = :pid AND market_product_nos ->> :acct = :val"
                    ),
                    {"pid": product_id, "acct": account_id, "val": claim_val},
                )
                await _s.commit()
        except Exception as _e:
            logger.warning(f"[{self.market_type}] 등록 선점 해제 실패(무시): {_e}")

    async def _persist_product_no_immediately(
        self, product_id: str, account_id: str, market_no: str
    ) -> None:
        """등록 성공 직후 __claiming__ 표식을 실제 마켓번호로 교체 (fresh session).

        대기 중인 동일 (상품,계정) 등록 잡이 3초 폴링에서 실제 번호를 즉시 확인하도록
        별도 세션으로 즉시 커밋. worker 측 최종 writeback 과 멱등(같은 값) — 무해.
        """
        if not (product_id and account_id and market_no):
            return
        try:
            from sqlalchemy import text as _t
            from backend.db.orm import get_write_session as _gws

            async with _gws() as _s:
                await _s.execute(
                    _t(
                        "UPDATE samba_collected_product SET "
                        "  market_product_nos = COALESCE(market_product_nos, '{}'::jsonb) "
                        "    || jsonb_build_object(CAST(:acct AS text), to_jsonb(CAST(:no AS text))), "
                        "  registered_accounts = CASE "
                        "    WHEN registered_accounts @> jsonb_build_array(CAST(:acct AS text)) "
                        "      THEN registered_accounts "
                        "    ELSE COALESCE(registered_accounts, '[]'::jsonb) "
                        "      || jsonb_build_array(CAST(:acct AS text)) "
                        "  END "
                        "WHERE id = CAST(:pid AS text)"
                    ),
                    {"acct": account_id, "no": market_no, "pid": product_id},
                )
                await _s.commit()
        except Exception as _e:
            logger.warning(
                f"[{self.market_type}] 등록 후 즉시기록 실패(worker 기록에 위임): {_e}"
            )

    async def handle(
        self, session, product: dict, category_id: str, account, existing_no: str = ""
    ) -> dict[str, Any]:
        """마켓 전송 진입점."""
        creds = await self._load_auth(session, account)
        if not creds:
            return {"success": False, "message": f"{self.market_type} 인증정보 없음"}
        category_id = self._validate_category(category_id)
        product = await self._apply_market_settings(session, product, account)
        # 마켓별 카테고리 자동결정 훅 — 매핑이 없을 때 상품 정보로 카테고리를 채운다.
        # (GS샵: 소싱 카테고리 → prdClsCd|sectId 자동매칭) 검증 전에 호출되어야 함.
        category_id = await self._resolve_category(
            session, product, category_id, account
        )
        if not category_id:
            return {
                "success": False,
                "message": f"{self.market_type} 카테고리 코드 없음",
            }
        # DB 읽기 완료 — HTTP API 호출 전 트랜잭션 종료 (idle in transaction 방지)
        try:
            await session.commit()
        except Exception:
            pass
        try:
            return await self.execute(
                session, product, creds, category_id, account, existing_no
            )
        except Exception as e:
            return {
                "success": False,
                "error_type": self._classify_error(e),
                "message": str(e),
            }

    async def _resolve_category(
        self, session, product: dict, category_id: str, account
    ) -> str:
        """마켓별 카테고리 자동결정 훅. 기본은 그대로 반환.
        매핑 테이블 없이 상품 정보로 카테고리를 채우는 마켓(GS샵)이 오버라이드.
        """
        return category_id

    def _classify_error(self, exc: Exception) -> str:
        """에러 유형 분류."""
        msg = str(exc).lower()
        if "401" in msg or "403" in msg or "token" in msg:
            return "auth_failed"
        if "timeout" in msg or "connect" in msg:
            return "network"
        if "400" in msg or "invalid" in msg:
            return "schema_changed"
        return "unknown"

    async def _load_auth(self, session, account) -> dict | None:
        """인증정보 로드 — account 우선, account 없을 때만 settings 폴백.
        account가 명시됐는데 credentials가 없으면 None 반환 (다른 계정으로 오인 전송 방지).
        """
        creds = {}
        if account:
            extras = account.additional_fields or {}
            creds = {k: v for k, v in extras.items() if v}
            # additional_fields 내용과 무관하게 컬럼값 보충 (없는 키만 추가)
            if account.api_key and "apiKey" not in creds:
                creds["apiKey"] = account.api_key
            if account.api_secret and "apiSecret" not in creds:
                creds["apiSecret"] = account.api_secret
            if account.seller_id and "sellerId" not in creds:
                creds["sellerId"] = account.seller_id
            # account 지정됐으나 credentials 없으면 폴백 없이 None 반환
            return creds or None
        # account가 None인 경우에만 SambaSettings 폴백 (레거시 단일계정)
        from backend.domain.samba.forbidden.model import SambaSettings
        from sqlmodel import select

        stmt = select(SambaSettings).where(
            SambaSettings.key == f"store_{self.market_type}"
        )
        result = await session.execute(stmt)
        row = result.scalars().first()
        if row and isinstance(row.value, dict):
            creds = row.value
        return creds or None

    def _validate_category(self, category_id: str) -> str:
        """카테고리 코드 유효성 검증."""
        if category_id and not category_id.isdigit():
            return ""
        return category_id

    async def _apply_market_settings(self, session, product: dict, account) -> dict:
        """정책에서 마켓별 설정 주입."""
        policy_id = product.get("applied_policy_id")
        if not policy_id:
            return product
        from backend.domain.samba.policy.repository import SambaPolicyRepository

        policy_repo = SambaPolicyRepository(session)
        policy = await policy_repo.get_async(policy_id)
        if policy and policy.market_policies:
            mp = policy.market_policies.get(self.policy_key, {})
            if mp.get("shippingCost"):
                product["_delivery_fee_type"] = "PAID"
                product["_delivery_base_fee"] = int(mp["shippingCost"])
            if mp.get("maxStock"):
                product["_max_stock"] = mp["maxStock"]
            # SSG 주문수량 제한 (정책 → 상품에 주입)
            if mp.get("dayMaxQty"):
                product["_day_max_qty"] = int(mp["dayMaxQty"])
            if mp.get("onceMinQty"):
                product["_once_min_qty"] = int(mp["onceMinQty"])
            if mp.get("onceMaxQty"):
                product["_once_max_qty"] = int(mp["onceMaxQty"])
        if account:
            extras = account.additional_fields or {}
            if extras.get("asPhone"):
                product["_as_phone"] = extras["asPhone"]
        return product

    @abstractmethod
    async def execute(
        self,
        session,
        product: dict,
        creds: dict,
        category_id: str,
        account,
        existing_no: str,
    ) -> dict[str, Any]:
        """마켓 API 호출 (등록/수정)."""
        ...

    @abstractmethod
    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        """상품 데이터 -> 마켓 API 포맷 변환."""
        ...

    async def delete(self, session, product_no: str, account) -> dict[str, Any]:
        """마켓 상품 삭제 — 기본은 미지원."""
        return {"success": False, "message": f"{self.market_type} 삭제 미지원"}

    async def test_auth(self, session, account) -> bool:
        """인증 테스트 — 기본은 항상 성공."""
        return True
