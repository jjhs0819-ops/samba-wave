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

# POIZON 신규 셀러 제약 — SKU당 재고 1개 초과 등록 시 거부됨(첫 거래 완료 전까지 유지).
_NEW_SELLER_QTY_CAP = 1


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


def merge_poison_sizes(
    prev: Any, new: dict[str, Any], cancelled: list[str] | None = None
) -> dict[str, Any]:
    """기존 사이즈 매핑에 이번 결과를 병합한다.

    통째 교체하면 시세 게이트 스킵·API 거부로 일부만 성공했을 때 나머지 사이즈의
    biddingNo 가 사라진다 → 다음 사이클이 신규 등록으로 오판(91800500 중복 거부),
    품절이 나도 취소할 번호가 없어 오버셀. 실제 유실 사고로 확인됨(2026-08-19).
    """
    merged: dict[str, Any] = {}
    if isinstance(prev, dict):
        merged.update({k: v for k, v in prev.items()})
    merged.update(new or {})
    for size in cancelled or []:
        entry = dict(merged.get(size) or {})
        entry.pop("biddingNo", None)
        entry["status"] = "cancelled"
        merged[size] = entry
    return merged


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

        from backend.domain.samba.proxy.poison import PoisonClient, option_real_cost

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

        # 1. 카탈로그 SKU 조회 (색상·사이즈별 globalSkuId)
        #    소싱처가 품번 뒤에 내부코드를 붙인 경우가 많아 정제본까지 시도한다.
        #    language="en" — 색상 매칭(아래)이 영문 색상명을 기준으로 한다.
        sku_list, matched_article = await client.query_sku_by_article_number_any(
            article_number, language="en"
        )
        if matched_article and matched_article != article_number:
            logger.info(
                f"[POIZON] 품번 정제 매칭: {article_number} → {matched_article}"
            )
            article_number = matched_article
        #    접미사 후보로도 못 찾으면 하이픈/언더바 뒤를 통째로 떼고 재시도한다
        #    (무신사 등은 style_code 에 색상 접미사를 붙여 저장: LM5AO4S-0001)
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
                    article_number = base_article
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
                    article_number = base_article
                    sku_list = alt
        if not sku_list:
            return {
                "success": False,
                "message": f"POIZON 카탈로그에 품번 '{article_number}' 없음 (등록 대상 아님)",
            }

        # 사이즈 표기체계(EU/KR/mm 등) 우선순위 인덱스 — 색상 매칭 실패 시 폴백
        size_index = build_size_index(sku_list)
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
        # 옵션가 불균일 대응 — 무신사 등은 같은 상품이라도 사이즈마다 판매가가 다르다
        # (할인 적용 PLUS 옵션 vs 정가 NORMAL 옵션). product.cost 는 최저옵션가 기준이라
        # 비싼 옵션을 그 원가로 등록하면 팔리는 순간 확정 역마진이 난다.
        # (2026-08-19 IY7278 실사고: 원가 53,990 으로 89,000 등록 → 실매입 109,000, -35,000)
        _opt_prices = [
            self._safe_int(o.get("price"))
            for o in options
            if isinstance(o, dict) and self._safe_int(o.get("price")) > 0
        ]
        min_opt_price = min(_opt_prices) if _opt_prices else 0
        results: list[dict[str, Any]] = []
        new_sizes: dict[str, Any] = {}
        cancelled_sizes: list[str] = []

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
            cost = self._safe_int(opt.get("cost"))
            if not cost:
                # 최저옵션 대비 비싼 옵션 — 같은 할인율로 실매입가를 환산한다
                cost = option_real_cost(
                    fallback_cost, self._safe_int(opt.get("price")), min_opt_price
                )
            norm = _normalize_size(opt_name)

            # 색상+사이즈 이중 매칭 시도
            sku = None
            size_source = ""
            if product_color and norm:
                # 1) 상품색상 + 사이즈 정확 매칭
                sku = color_size_index.get((product_color, norm))
                if not sku and product_color and norm in size_only_index:
                    # 2) 색상 정확 매칭 실패 → 색상 키워드 부분매칭(BLK→블랙, GREY→그레이)
                    for (c, s_) in list(color_size_index.keys()):
                        if s_ == norm and product_color in c.upper():
                            sku = color_size_index[(c, s_)]
                            break
                    # 3) 여전히 못 찾으면 → 영문/한글 혼합 색상(Solar Grey→솔라 그레이)
                    if not sku:
                        for (c, s_), candidate in color_size_index.items():
                            if s_ == norm:
                                # 영문 키워드 포함 (GREY, BLACK 등)
                                for kw in product_color.split():
                                    if kw and len(kw) > 2 and kw in c.upper():
                                        sku = candidate
                                        break
                            if sku:
                                break
                if sku:
                    size_source = "색상+사이즈"
            if not sku:
                # 4) 색상 미추출 또는 색상 매칭 실패 → 사이즈 표기체계 인덱스로 폴백
                #    (EU/KR/mm 우선순위 — 신발처럼 표기체계가 여러 개인 경우 필수)
                matched = size_index.get(norm)
                if matched:
                    sku, size_source = matched
            if not sku:
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
                    if r.get("success"):
                        cancelled_sizes.append(opt_name)
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
                # 이미 걸려 있는 입찰이면 반드시 내린다 — 안 내리면 수익이 안 나는
                # 가격표가 그대로 살아남아 계속 팔린다(2026-08-19 IY7278 사고).
                if bidding_no:
                    c = await client.cancel_listing(bidding_no)
                    if c.get("success"):
                        cancelled_sizes.append(opt_name)
                    logger.info(
                        f"[POIZON] 게이트 탈락 입찰 취소 {article_number}/{opt_name} "
                        f"원가={int(cost)} → {c.get('message')}"
                    )
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
                    # POIZON은 수정 성공 시 신규 sellerBiddingNo를 발급(구 번호 만료).
                    # 응답에 없으면(no_change 등) 기존 번호를 유지한다.
                    new_sizes[opt_name] = {
                        "globalSkuId": int(global_sku_id),
                        "biddingNo": str(r.get("sellerBiddingNo") or "") or bidding_no,
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
            session,
            product.get("id"),
            article_number,
            new_sizes,
            _time.time(),
            cancelled_sizes=cancelled_sizes,
            prev_sizes=prev_sizes,
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
        cancelled_sizes: list[str] | None = None,
        prev_sizes: dict[str, Any] | None = None,
    ) -> None:
        """resell_matches.poison 에 사이즈별 biddingNo 매칭 저장 (타 플랫폼 키 보존).

        ★sizes 는 **병합**한다. 이번 호출에서 성공한 사이즈만 담긴 dict 로 통째
        교체하면, 시세 게이트 스킵·API 거부 등으로 일부만 성공했을 때 나머지 사이즈의
        biddingNo 가 DB 에서 사라진다. 그러면 다음 사이클은 '기존 입찰 없음'으로 보고
        신규 등록을 시도해 91800500(중복)으로 막히고, 품절이 나도 취소할 번호가 없어
        오버셀로 이어진다. 실제로 라이브 입찰 6건이 이 경로로 유실됐다(2026-08-19).

        취소에 성공한 사이즈만 명시적으로 status='cancelled' 처리하고 biddingNo 를 비운다
        (재입고 시 execute 가 신규 manual_listing 분기를 타게 하는 기존 규약 유지).
        """
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
            _prev_raw = existing_pm.get("sizes")
            if not isinstance(_prev_raw, dict):
                _prev_raw = prev_sizes if isinstance(prev_sizes, dict) else {}
            merged = merge_poison_sizes(_prev_raw, sizes, cancelled_sizes)
            _has_live = has_live_bidding({"sizes": merged})
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
                "product_id": article_number if _has_live else "",
                "confidence": 100 if _has_live else 0,
                "articleNumber": article_number,
                "sizes": merged,
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
