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
from backend.domain.samba.proxy.poison import POISON_MIN_PROFIT, decide_bid_price
from backend.utils.logger import logger


def _normalize_size(text: str) -> str:
    """사이즈 비교용 정규화 — 단위/공백/대소문자 제거."""
    s = (text or "").upper().strip()
    for unit in ("MM", "EU", "US", "UK", "CN", "JP", "SIZE"):
        s = s.replace(unit, "")
    return re.sub(r"\s+", "", s)


# 사이즈 표기 우선순위 — 브랜드마다 주는 후보가 다르다.
# 뉴발란스는 KR(225), 나이키 신발은 CHN(225)만, 나이키 의류는 JP M 만 준다.
# 우선순위를 고정하지 않으면 먼저 들어온 표기가 이겨서 어느 체계로 매칭됐는지
# 통제가 안 된다. KR(우리 옵션과 같은 체계)을 최우선으로 둔다.
_SIZE_SOURCE_PRIORITY = {
    "KR": 0,
    "CHN": 1,
    "CN": 1,
    "EU": 2,
    "SIZE": 3,
    "US": 4,
    "US MEN": 4,
    "US WOMEN": 5,
    "UK": 6,
    "FR": 7,
    "IT": 7,
    "JP": 8,  # JP 알파벳 사이즈(JP M)는 KR 과 실측이 다를 수 있어 가장 나중
}
_SIZE_VALUE_PRIORITY = 50  # sizeValue 는 후보가 하나도 없을 때의 최후 수단


def has_live_bidding(poison_match: Any) -> bool:
    """이미 POIZON 에 살아있는 내 입찰이 있는가 (사이즈별 biddingNo 보유)."""
    if not isinstance(poison_match, dict):
        return False
    sizes = poison_match.get("sizes")
    if not isinstance(sizes, dict):
        return False
    for entry in sizes.values():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("biddingNo") or "") and entry.get("status") != "cancelled":
            return True
    return False


def should_skip_non_primary(poison_match: Any) -> bool:
    """최저가 소싱처가 아니라 '신규 등록'을 건너뛸 상품인지.

    같은 품번이 소싱처마다 별도상품으로 존재해 전부 등록하면 POIZON 중복 listing 이
    된다. 그래서 최저가 소싱처(is_primary)만 등록한다 — 단 이건 **신규 등록** 억제용이다.

    이미 내가 등록한 입찰이 있으면 무조건 통과시킨다. 등록 직후 _save_poison_match 가
    product_id 를 채우는데, is_primary 를 채우는 코드는 아직 어디에도 없어서(라이브
    355건 전량 키 없음) 기등록분이 여기서 영구 차단됐다. 그 결과 오토튠이 가격·재고를
    한 번도 반영하지 못하고 오버셀/역마진에 노출됐다.
    """
    if not isinstance(poison_match, dict):
        return False
    if not poison_match.get("product_id"):
        return False
    if poison_match.get("is_primary") is True:
        return False
    return not has_live_bidding(poison_match)


def build_size_index(
    sku_list: list[dict[str, Any]],
) -> dict[str, tuple[dict[str, Any], str]]:
    """사이즈 문자열 → (SKU, 매칭에 쓰인 표기체계).

    같은 문자열을 여러 SKU·체계가 주장하면 우선순위가 높은 쪽이 이긴다.
    어느 체계로 매칭됐는지 함께 돌려줘서 로그로 추적할 수 있게 한다.
    """
    best: dict[str, tuple[dict[str, Any], str, int]] = {}

    def put(raw: Any, sku: dict[str, Any], source: str, prio: int) -> None:
        key = _normalize_size(str(raw or ""))
        if not key:
            return
        cur = best.get(key)
        if cur is None or prio < cur[2]:
            best[key] = (sku, source, prio)

    for sku in sku_list:
        for source, val in (sku.get("sizeCandidates") or {}).items():
            src = str(source).strip().upper()
            put(val, sku, str(source), _SIZE_SOURCE_PRIORITY.get(src, 9))
        put(sku.get("sizeValue"), sku, "sizeValue", _SIZE_VALUE_PRIORITY)

    return {k: (v[0], v[1]) for k, v in best.items()}


class PoisonPlugin(MarketPlugin):
    market_type = "poison"
    policy_key = "포이즌"
    required_fields = ["name", "sale_price"]

    async def _load_auth(self, session, account) -> dict | None:
        """POIZON 인증 로드 — account.additional_fields 우선, store_poison 폴백."""
        if account:
            # 필드명이 제각각(appKey/apiKey/app_key/최상위 api_key)이라 공통 함수로 통일
            from backend.domain.samba.proxy.poison import extract_credentials

            app_key, app_secret = extract_credentials(account)
            if app_key and app_secret:
                return {"app_key": app_key, "app_secret": app_secret}
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

        # 최저가 소싱처(is_primary)만 신규 등록 — 기등록분(라이브 입찰 보유)은 통과.
        _resell = product.get("resell_matches") or {}
        _pm = _resell.get("poison") if isinstance(_resell, dict) else None
        if should_skip_non_primary(_pm):
            return {
                "success": False,
                "skip": True,
                "message": f"POIZON 최저가 소싱처 아님(품번 {article_number}) — 등록 스킵",
            }

        client = PoisonClient(app_key=str(app_key), app_secret=str(app_secret))

        # 1. 카탈로그 SKU 조회 (사이즈별 globalSkuId)
        #    소싱처가 품번 뒤에 내부코드를 붙인 경우가 많아 정제본까지 시도한다
        sku_list, matched_article = await client.query_sku_by_article_number_any(
            article_number
        )
        if matched_article and matched_article != article_number:
            logger.info(
                f"[POIZON] 품번 정제 매칭: {article_number} → {matched_article}"
            )
            article_number = matched_article
        if not sku_list:
            return {
                "success": False,
                "message": f"POIZON 카탈로그에 품번 '{article_number}' 없음 (등록 대상 아님)",
            }

        size_index = build_size_index(sku_list)

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

        # 시세 게이트용 사이즈별 시장가 — 재고 있는 사이즈만 일괄 조회(상품당 1~2회)
        min_profit = await self._load_min_profit(session, product)
        gate_ids: list[int] = []
        for opt in options:
            if self._safe_int(opt.get("stock"), default=0) <= 0:
                continue
            norm = _normalize_size((opt.get("name") or opt.get("size") or "").strip())
            matched = size_index.get(norm)
            gid = (matched[0] if matched else {}).get("globalSkuId")
            if gid:
                gate_ids.append(int(gid))
        market_map: dict[int, dict[str, Any]] = {}
        if gate_ids:
            try:
                market_map = await client.recommend_price_batch(
                    global_sku_ids=gate_ids
                )
            except Exception as e:  # 시세 조회 실패는 등록을 막지 않는다(하한만 방어)
                logger.warning(f"[POIZON] 시세 일괄조회 실패 — 게이트 우회: {e}")

        for opt in options:
            opt_name = (opt.get("name") or opt.get("size") or "").strip()
            stock = self._safe_int(opt.get("stock"), default=0)
            cost = self._safe_int(opt.get("cost")) or fallback_cost
            norm = _normalize_size(opt_name)
            matched = size_index.get(norm)
            sku, size_source = matched if matched else ({}, "")
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

            target = await self._compute_bid_price(
                session, product, cost, fee_rate, min_fee, ignore_common
            )
            if target <= 0:
                continue

            # 시세 게이트 — 시장가보다 비싸면 노출조차 안 되므로 시장가까지 내려서 등록하고,
            # 시장가로 팔아도 순이익 하한에 못 미치면 등록하지 않는다.
            # 등록가는 KRW 최소단위(1000원) 배수여야 하므로 unit 보정도 여기서 처리한다.
            market_price = (market_map.get(int(global_sku_id)) or {}).get("minPrice")
            decision = decide_bid_price(
                cost=cost,
                target=target,
                market=market_price,
                # 이미 등록된 가격 — 시세가 이 값과 같으면 내 입찰이 되돌아온 것이다
                own_price=self._safe_int(prev_entry.get("price")) or None,
                min_profit=min_profit,
                unit=1000,
            )
            if decision.skipped:
                results.append(
                    {
                        "size": opt_name,
                        "success": False,
                        "skip": True,
                        "message": f"시세 게이트: {decision.reason}",
                    }
                )
                continue
            price = decision.price
            # 가격 결정 근거를 남긴다 — 나중에 "왜 이 값이 됐나"를 역추적하기 위함
            logger.info(
                f"[POIZON] 가격결정 {article_number}/{opt_name} 원가={int(cost)} "
                f"목표={int(target)} 시세={market_price or '없음'} "
                f"기존={prev_entry.get('price') or '없음'} 사이즈체계={size_source or '-'} "
                f"→ {price} ({decision.reason})"
            )

            if bidding_no:
                # 기존 입찰 → 가격/재고 수정
                r = await client.update_listing(
                    seller_bidding_no=bidding_no,
                    price=price,
                    quantity=stock,
                    global_sku_id=int(global_sku_id),
                )
                if r.get("success"):
                    new_sizes[opt_name] = {
                        "globalSkuId": int(global_sku_id),
                        "biddingNo": bidding_no,
                        "price": price,
                        "qty": stock,
                    }
            else:
                # 신규 등록
                r = await client.manual_listing(
                    global_sku_id=int(global_sku_id),
                    price=price,
                    quantity=stock,
                )
                if r.get("success") and r.get("sellerBiddingNo"):
                    new_sizes[opt_name] = {
                        "globalSkuId": int(global_sku_id),
                        "biddingNo": str(r["sellerBiddingNo"]),
                        "price": price,
                        "qty": stock,
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

    async def _load_min_profit(self, session, product: dict) -> int:
        """정책에서 건당 최소 순이익(원) 로드. 미설정이면 기본값."""
        policy_id = product.get("applied_policy_id")
        if not policy_id:
            return POISON_MIN_PROFIT
        from backend.domain.samba.policy.repository import SambaPolicyRepository

        try:
            policy = await SambaPolicyRepository(session).get_async(policy_id)
        except Exception:
            return POISON_MIN_PROFIT
        if not policy or not policy.market_policies:
            return POISON_MIN_PROFIT
        mp = policy.market_policies.get(self.policy_key) or {}
        val = mp.get("minProfitAmount")
        return int(val) if val not in (None, "") else POISON_MIN_PROFIT

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
            rm["poison"] = {
                # 상품관리 UI(resellRows)가 읽는 키 — 등록된 사이즈 있으면 매칭표시
                "product_id": article_number if sizes else "",
                "confidence": 100 if sizes else 0,
                "articleNumber": article_number,
                "sizes": sizes,
                "updated_at": int(ts),
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
