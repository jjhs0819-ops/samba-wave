"""POIZON(포이즌) 마켓 플러그인.

KREAM과 동일한 카탈로그형 리셀 구조:
브랜드 공식품번(style_code)으로 POIZON 카탈로그 globalSkuId를 조회한 뒤,
사이즈별로 Manual Listing(Ship-to-verify) 판매 등록을 한다.

인증: app_key/app_secret (account 필드 또는 store_poison 설정에서 로드).
"""

from __future__ import annotations

import re
from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.utils.logger import logger

# POIZON 신규 셀러 제약 — SKU당 재고 1개 초과 등록 시 거부됨(첫 거래 완료 전까지 유지).
_NEW_SELLER_QTY_CAP = 1


def _normalize_size(text: str) -> str:
    """사이즈 비교용 정규화 — 단위/공백/대소문자 제거."""
    s = (text or "").upper().strip()
    for unit in ("MM", "EU", "US", "UK", "CN", "JP", "SIZE"):
        s = s.replace(unit, "")
    return re.sub(r"\s+", "", s)


class PoisonPlugin(MarketPlugin):
    market_type = "poison"
    policy_key = "포이즌"
    required_fields = ["name", "sale_price"]

    async def _load_auth(self, session, account) -> dict | None:
        """POIZON 인증 로드 — account.additional_fields 우선, store_poison 폴백."""
        if account:
            extras = account.additional_fields or {}
            # additional_fields 키: appKey(구), apiKey(신 프론트 저장명) 모두 허용
            app_key = (
                extras.get("appKey") or extras.get("apiKey") or account.api_key or ""
            )
            app_secret = (
                extras.get("appSecret")
                or extras.get("apiSecret")
                or account.api_secret
                or ""
            )
            if app_key and app_secret:
                return {"app_key": str(app_key), "app_secret": str(app_secret)}
            # account 지정됐으나 인증정보 없으면 폴백 없이 None (오인 전송 방지)
            return None

        # 레거시 단일계정 — store_poison 설정 폴백
        from sqlmodel import select

        from backend.domain.samba.forbidden.model import SambaSettings

        stmt = select(SambaSettings).where(SambaSettings.key == "store_poison")
        result = await session.execute(stmt)
        row = result.scalars().first()
        try:
            await session.commit()
        except Exception:
            pass
        if row and isinstance(row.value, dict):
            app_key = (
                row.value.get("appKey")
                or row.value.get("app_key")
                or row.value.get("apiKey")
                or ""
            )
            app_secret = (
                row.value.get("appSecret")
                or row.value.get("app_secret")
                or row.value.get("apiSecret")
                or ""
            )
            if app_key and app_secret:
                return {"app_key": str(app_key), "app_secret": str(app_secret)}
        return None

    def _validate_category(self, category_id: str) -> str:
        """POIZON은 카탈로그(globalSkuId)로 등록 — 마켓 카테고리 코드 불필요."""
        return category_id or "0"

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        """POIZON은 카탈로그 매칭 방식 — 별도 변환 없이 원본 사용."""
        return product

    async def execute(
        self,
        session,
        product: dict,
        creds: dict,
        category_id: str,
        account,
        existing_no: str,
    ) -> dict[str, Any]:
        """품번 카탈로그 매칭 후 사이즈별 등록/수정/취소.

        오토튠 재전송 시 resell_matches.poison 에 저장된 sellerBiddingNo 로
        - 재고 0 → 취소(Cancel Listing)
        - 기존 입찰 있음 → 수정(Update Manual Listing)
        - 신규 → 등록(Manual Listing) 후 biddingNo 저장
        가격은 정책(수수료/최소수수료/공통마진무시)으로 계산.
        """
        import time as _time

        from backend.domain.samba.proxy.poison import PoisonClient

        app_key = (
            creds.get("app_key") or creds.get("appKey") or creds.get("apiKey") or ""
        )
        app_secret = (
            creds.get("app_secret")
            or creds.get("appSecret")
            or creds.get("apiSecret")
            or ""
        )
        if not app_key or not app_secret:
            return {
                "success": False,
                "message": "POIZON 인증 정보(app_key/app_secret)가 없습니다.",
            }

        article_number = str(
            product.get("style_code")
            or product.get("styleCode")
            or product.get("model_no")
            or ""
        ).strip()
        if not article_number:
            return {
                "success": False,
                "message": "POIZON 매칭용 품번(style_code)이 없습니다.",
            }

        # 최저가 소싱처(is_primary)만 등록 — 같은 품번이 소싱처마다 별도상품으로 존재,
        # 전부 등록하면 POIZON 중복 listing. 매칭됐는데 primary 아니면 스킵.
        _resell = product.get("resell_matches") or {}
        _pm = _resell.get("poison") if isinstance(_resell, dict) else None
        if (
            isinstance(_pm, dict)
            and _pm.get("product_id")
            and _pm.get("is_primary") is not True
        ):
            return {
                "success": False,
                "skip": True,
                "message": f"POIZON 최저가 소싱처 아님(품번 {article_number}) — 등록 스킵",
            }

        client = PoisonClient(app_key=str(app_key), app_secret=str(app_secret))

        # 1. 카탈로그 SKU 조회 (색상·사이즈별 globalSkuId)
        #    무신사 등 일부 소싱처는 style_code 에 색상 접미사를 붙여 저장한다.
        #    원본 우선 조회 → 실패 시 하이픈 제거(LM5AO4S-0001→LM5AO4S) 재시도 →
        #    실패 시 언더바 제거(_NAVY→) 재시도.
        #    (full-first: Nike/Adidas 등 접미사 없는 정품번은 1차 조회로 잡혀 영향 없음)
        sku_list = await client.query_sku_by_article_number(
            article_number, language="en"
        )
        article_used = article_number
        if not sku_list and "-" in article_number:
            base_article = article_number.rsplit("-", 1)[0].strip()
            if base_article and base_article != article_number:
                alt = await client.query_sku_by_article_number(
                    base_article, language="en"
                )
                if alt:
                    logger.info(
                        f"[POIZON] 품번 하이픈 폴백: '{article_number}' → '{base_article}'"
                    )
                    article_used = base_article
                    sku_list = alt
        if not sku_list and "_" in article_number:
            base_article = article_number.rsplit("_", 1)[0].strip()
            if base_article and base_article != article_number:
                alt = await client.query_sku_by_article_number(
                    base_article, language="en"
                )
                if alt:
                    logger.info(
                        f"[POIZON] 품번 언더바 폴백: '{article_number}' → '{base_article}'"
                    )
                    article_used = base_article
                    sku_list = alt
        if not sku_list:
            return {
                "success": False,
                "message": f"POIZON 카탈로그에 품번 '{article_number}' 없음 (등록 대상 아님)",
            }

        # 색상+사이즈 → SKU 인덱스 (멀티컬러 의류용)
        # query_sku_by_article_number가 이미 파싱한 color/sizeValue 사용
        color_size_index: dict[tuple[str, str], dict[str, Any]] = {}
        size_only_index: dict[str, dict[str, Any]] = {}
        for sku in sku_list:
            color = (sku.get("color") or "").strip().upper()
            size = _normalize_size(sku.get("sizeValue") or "")
            if size:
                size_only_index.setdefault(size, sku)
            if color and size:
                color_size_index[(color, size)] = sku

        # 상품 색상 추출 — DB color 필드 > name 마지막 단어 > style_code "-" 뒤
        product_color = ""
        # 1) DB color 필드 우선 (무신사 "Solar Grey" 등 정확한 색상명)
        if product.get("color"):
            product_color = str(product.get("color")).strip().upper()
        # 2) name 마지막 단어 폴백 (예: "... BLK")
        if not product_color and product.get("name"):
            parts = (product.get("name") or "").split()
            if parts:
                product_color = parts[-1].upper()
        # 3) style_code "-" 뒤 폴백 (숫자 제외)
        if not product_color:
            original_style = str(product.get("style_code") or "")
            if "-" in original_style:
                candidate = original_style.rsplit("-", 1)[1].strip().upper()
                if candidate and not candidate.isdigit():
                    product_color = candidate
        if product_color:
            logger.info(f"[POIZON] 상품 색상 추출: {product_color}")

        # 이전 등록 매칭(사이즈별 sellerBiddingNo) — 오토튠 수정/취소용
        resell = product.get("resell_matches") or {}
        prev = (resell.get("poison") if isinstance(resell, dict) else None) or {}
        prev_sizes = prev.get("sizes") if isinstance(prev, dict) else {}
        if not isinstance(prev_sizes, dict):
            prev_sizes = {}

        # 정책 (수수료율 / 최소수수료 / 공통마진 무시)
        fee_rate, min_fee, ignore_common = await self._load_poison_policy(
            session, product
        )

        options = product.get("options") or []
        fallback_cost = self._safe_int(product.get("cost")) or self._safe_int(
            product.get("sale_price")
        )
        results: list[dict[str, Any]] = []
        new_sizes: dict[str, Any] = {}

        for opt in options:
            opt_name = (opt.get("name") or opt.get("size") or "").strip()
            stock = self._safe_int(opt.get("stock"), default=0)
            cost = self._safe_int(opt.get("cost")) or fallback_cost
            norm = _normalize_size(opt_name)

            # 색상+사이즈 이중 매칭 시도
            sku = None
            if product_color and norm:
                # 1) 상품색상 + 사이즈 정확 매칭
                sku = color_size_index.get((product_color, norm))
                if not sku and product_color and norm in size_only_index:
                    # 2) 색상 정확 매칭 실패 → 색상 키워드 부분매칭(BLK→블랙, GREY→그레이)
                    for (c, s), candidate in color_size_index.items():
                        if s == norm and product_color in c.upper():
                            sku = candidate
                            break
                    # 3) 여전히 못 찾으면 → 영문/한글 혼합 색상(Solar Grey→솔라 그레이)
                    if not sku:
                        for (c, s), candidate in color_size_index.items():
                            if s == norm:
                                # 영문 키워드 포함 (GREY, BLACK 등)
                                for kw in product_color.split():
                                    if kw and len(kw) > 2 and kw in c.upper():
                                        sku = candidate
                                        break
                            if sku:
                                break
            if not sku:
                # 4) 색상 미추출 또는 색상 매칭 실패 → 사이즈만으로 폴백
                sku = size_only_index.get(norm)

            prev_entry = prev_sizes.get(opt_name) or prev_sizes.get(norm) or {}
            bidding_no = str(prev_entry.get("biddingNo") or "")
            global_sku_id = (sku or {}).get("globalSkuId") or prev_entry.get(
                "globalSkuId"
            )

            if not global_sku_id:
                results.append(
                    {"size": opt_name, "success": False, "message": "사이즈 매칭 실패"}
                )
                continue

            # 재고 0 → 기존 입찰 취소 (등록 안 된 사이즈는 skip)
            if stock <= 0:
                if bidding_no:
                    r = await client.cancel_listing(bidding_no)
                    r["size"] = opt_name
                    results.append(r)
                continue

            price = await self._compute_bid_price(
                session, product, cost, fee_rate, min_fee, ignore_common
            )
            if price <= 0:
                continue
            # POIZON 은 등록가가 통화 최소단위 배수여야 함(KRW=1000원). 배수가 아니면
            # "Invalid value. Must be a multiple of" 로 거부 → 1000원 단위 올림(마진 보존).
            price = -(-int(price) // 1000) * 1000

            # POIZON 신규 셀러는 SKU당 재고 1개까지만 등록 가능(첫 거래 완료 전까지).
            # 초과 수량 전송 시 "listing Qty is limited to 1 piece per SKU" 로 거부.
            qty = min(stock, _NEW_SELLER_QTY_CAP)

            if bidding_no:
                # 기존 입찰 → 가격/재고 수정
                r = await client.update_listing(
                    seller_bidding_no=bidding_no,
                    price=price,
                    quantity=qty,
                    global_sku_id=int(global_sku_id),
                )
                if r.get("success"):
                    # POIZON은 수정 성공 시 신규 sellerBiddingNo를 발급(구 번호 만료)
                    new_sizes[opt_name] = {
                        "globalSkuId": int(global_sku_id),
                        "biddingNo": str(r.get("sellerBiddingNo") or bidding_no),
                        "price": price,
                        "qty": qty,
                    }
            else:
                # 신규 등록
                r = await client.manual_listing(
                    global_sku_id=int(global_sku_id),
                    price=price,
                    quantity=qty,
                )
                if r.get("success") and r.get("sellerBiddingNo"):
                    new_sizes[opt_name] = {
                        "globalSkuId": int(global_sku_id),
                        "biddingNo": str(r["sellerBiddingNo"]),
                        "price": price,
                        "qty": qty,
                    }
            r["size"] = opt_name
            results.append(r)

        # resell_matches.poison 저장 (사이즈별 biddingNo) — 다음 오토튠 수정/취소 키
        await self._save_poison_match(
            session, product.get("id"), article_number, new_sizes, _time.time()
        )

        ok_count = sum(1 for r in results if r.get("success"))
        if ok_count == 0:
            err = next((r.get("message") for r in results if not r.get("success")), "")
            return {
                "success": False,
                "message": err or "POIZON 등록 실패",
                "data": results,
            }

        first_no = next(
            (s["biddingNo"] for s in new_sizes.values() if s.get("biddingNo")),
            "",
        )
        return {
            "success": True,
            "message": f"POIZON {ok_count}건 처리 (품번 {article_number})",
            "product_no": first_no,
            "data": results,
        }

    async def _load_poison_policy(
        self, session, product: dict
    ) -> tuple[float, int, bool]:
        """정책에서 포이즌 수수료율/최소수수료/공통마진무시 로드."""
        policy_id = product.get("applied_policy_id")
        if not policy_id:
            return 0.0, 0, False
        from backend.domain.samba.policy.repository import SambaPolicyRepository

        try:
            policy = await SambaPolicyRepository(session).get_async(policy_id)
        except Exception:
            return 0.0, 0, False
        if not policy or not policy.market_policies:
            return 0.0, 0, False
        mp = policy.market_policies.get(self.policy_key) or {}
        fee_rate = float(mp.get("feeRate") or 0)
        min_fee = int(mp.get("minFeeAmount") or 0)
        ignore_common = bool(mp.get("ignoreCommonMargin"))
        return fee_rate, min_fee, ignore_common

    async def _compute_bid_price(
        self,
        session,
        product: dict,
        cost: int,
        fee_rate: float,
        min_fee: int,
        ignore_common: bool,
    ) -> int:
        """입찰가 계산.

        ignore_common=False → 정책 공통 마진(calculate_market_price) 적용.
        ignore_common=True  → 공통 마진 무시, 원가+수수료 그로스업만.
        최소수수료(min_fee): %수수료가 min_fee 미만이면 차액만큼 가격 상향(절대 최소 보장).
        """
        import math

        cost = max(int(cost or 0), 0)
        if cost <= 0:
            return self._safe_int(product.get("sale_price"))

        price = float(cost)
        if ignore_common:
            if 0 < fee_rate < 100:
                price = cost / (1 - fee_rate / 100)
        else:
            policy_id = product.get("applied_policy_id")
            if policy_id:
                from backend.domain.samba.policy.repository import SambaPolicyRepository
                from backend.domain.samba.policy.service import SambaPolicyService

                try:
                    svc = SambaPolicyService(SambaPolicyRepository(session))
                    price = float(
                        await svc.calculate_market_price(
                            policy_id,
                            float(cost),
                            fee_rate,
                            str(product.get("source_site") or ""),
                            product.get("tenant_id"),
                        )
                    )
                except Exception:
                    if 0 < fee_rate < 100:
                        price = cost / (1 - fee_rate / 100)
            elif 0 < fee_rate < 100:
                price = cost / (1 - fee_rate / 100)

        # 절대 최소수수료 보정
        if min_fee > 0:
            pct_fee = price * fee_rate / 100 if fee_rate > 0 else 0
            if pct_fee < min_fee:
                price += min_fee - pct_fee

        return int(math.ceil(price))

    async def _save_poison_match(
        self,
        session,
        product_id: str | None,
        article_number: str,
        sizes: dict[str, Any],
        ts: float,
    ) -> None:
        """resell_matches.poison 에 사이즈별 biddingNo 매칭 저장 (타 플랫폼 키 보존)."""
        if not product_id:
            return
        from backend.domain.samba.collector.repository import (
            SambaCollectedProductRepository,
        )

        try:
            repo = SambaCollectedProductRepository(session)
            row = await repo.get_async(product_id)
            if not row:
                return
            rm = dict(row.resell_matches or {})
            existing_pm = rm.get("poison") or {}
            # is_primary: 소싱처간 최저가 비교 기능은 아직 미구현이라 이 값을 True로
            # 세팅하는 곳이 여기뿐임. 저장 때마다 누락시키면 "최저가 소싱처 아님" 게이트가
            # 방금 성공한 자기 자신을 다음 전송(오토튠 재동기화 등)에서 막아버림 —
            # 기존값이 명시적으로 False(향후 비교 기능 도입 시)가 아닌 한 True 유지.
            is_primary = (
                existing_pm.get("is_primary")
                if isinstance(existing_pm, dict) and "is_primary" in existing_pm
                else True
            )
            rm["poison"] = {
                # 상품관리 UI(resellRows)가 읽는 키 — 등록된 사이즈 있으면 매칭표시
                "product_id": article_number if sizes else "",
                "confidence": 100 if sizes else 0,
                "articleNumber": article_number,
                "sizes": sizes,
                "updated_at": int(ts),
                "is_primary": is_primary,
            }
            row.resell_matches = rm
            await session.commit()
        except Exception as e:
            logger.warning(f"[POIZON] resell_matches 저장 실패(무시): {e}")
            try:
                await session.rollback()
            except Exception:
                pass

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
