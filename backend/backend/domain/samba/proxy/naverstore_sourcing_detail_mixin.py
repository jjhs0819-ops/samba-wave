"""네이버스토어 상품 상세 조회 믹스인.

`NaverStoreSourcingClient` 의 상세 관련 메서드를 격리한 mixin.
메인 클래스의 상태(BASE_URL, HEADERS, DETAIL_DELAY, _build_proxies,
_extract_product_id, _uid_cache_reverse, resolve_channel_uid,
_timeout, _last_channel_uid, _last_store_name)를 가정한다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from backend.domain.samba.proxy.naverstore_sourcing_parsers import (
    _clamp_stock,
    _parse_detail_product,
)
from backend.utils.logger import logger


class NaverStoreDetailMixin:
    """상품 상세 조회 인터페이스.

    `NaverStoreSourcingClient` 와 함께 사용하도록 설계됨.
    """

    async def get_detail(
        self,
        site_product_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """잡워커 호환 상세 조회 — 확장앱 SourcingQueue 경유.

        Cloud Run에서 curl_cffi/httpx 직접 호출은 /i/v2 상세 API에서 일괄 429 차단됨.
        실사용자 브라우저 확장앱만 통과 가능 → 확장앱이 폴링해서 탭 컨텍스트로 fetch.

        흐름:
          1) SourcingQueue.add_detail_job("NAVERSTORE", ...) 로 작업 등록
          2) 확장앱이 /sourcing/collect-queue 폴링 → 탭 열고 /i/v2/... fetch
          3) 확장앱이 /sourcing/collect-result 로 raw product JSON 전달
          4) 여기서 _parse_detail_product()로 snake_case 변환해 반환
        """
        from backend.domain.samba.proxy.sourcing_queue import SourcingQueue

        channel_uid = kwargs.get("channel_uid") or getattr(
            self, "_last_channel_uid", ""
        )
        store_name = getattr(self, "_last_store_name", "") or kwargs.get(
            "store_name", ""
        )

        if not channel_uid or not store_name:
            logger.warning(
                f"[NAVERSTORE-DETAIL] channel_uid/store_name 누락: "
                f"pid={site_product_id} channel='{channel_uid}' store='{store_name}'"
            )
            return {}

        product_url = (
            kwargs.get("source_url")
            or f"{self.BASE_URL}/{store_name}/products/{site_product_id}"  # type: ignore[attr-defined]
        )

        request_id, future = SourcingQueue.add_detail_job(
            "NAVERSTORE",
            site_product_id,
            url=product_url,
            extra={
                "channelUid": channel_uid,
                "storeName": store_name,
            },
        )
        logger.info(
            f"[NAVERSTORE-DETAIL] 큐 등록: pid={site_product_id} "
            f"channel={channel_uid[:10]}... req={request_id}"
        )

        try:
            data = await asyncio.wait_for(future, timeout=90.0)
        except asyncio.TimeoutError:
            SourcingQueue.resolvers.pop(request_id, None)
            logger.warning(
                f"[NAVERSTORE-DETAIL] 타임아웃(90s) — 확장앱 미동작? pid={site_product_id}"
            )
            return {}

        if not isinstance(data, dict) or not data.get("success"):
            msg = (
                data.get("message", "알 수 없는 오류")
                if isinstance(data, dict)
                else "응답 형식 오류"
            )
            logger.warning(f"[NAVERSTORE-DETAIL] 확장앱 실패: {msg}")
            return {}

        product_data = data.get("data") or {}
        if not isinstance(product_data, dict) or not product_data.get("id"):
            logger.warning(
                f"[NAVERSTORE-DETAIL] raw data 비정상: keys={list(product_data.keys())[:10] if isinstance(product_data, dict) else type(product_data).__name__}"
            )
            return {}

        result = _parse_detail_product(product_data, site_product_id, store_name)
        logger.info(
            f"[NAVERSTORE-DETAIL] 완료: name='{result.get('name', '')[:30]}' "
            f"images={len(result.get('images', []))} options={len(result.get('options', []))}"
        )
        return result

    # ------------------------------------------------------------------
    # 상품 상세 조회 (직접 API — 프록시/쿠키 모드)
    # ------------------------------------------------------------------

    async def get_product_detail(
        self,
        product_url_or_id: str,
        channel_uid: Optional[str] = None,
        cookies: Optional[str] = None,
    ) -> dict[str, Any]:
        """네이버스토어 상품 상세 정보 조회 (JSON API).

        Args:
            product_url_or_id: 상품 URL 또는 상품ID
            channel_uid: channelUid (없으면 URL에서 추출)

        Returns:
            표준 상품 상세 dict
        """
        # URL에서 productId와 channelUid 추출
        if product_url_or_id.startswith("http"):
            product_id = self._extract_product_id(product_url_or_id)  # type: ignore[attr-defined]
            if not channel_uid:
                channel_uid = await self.resolve_channel_uid(product_url_or_id)  # type: ignore[attr-defined]
        else:
            product_id = product_url_or_id

        if not product_id:
            logger.error(f"[NAVERSTORE] 상품ID 추출 실패: {product_url_or_id}")
            return {}

        if not channel_uid:
            logger.error(f"[NAVERSTORE] channelUid 없음: {product_url_or_id}")
            return {}

        store_name = self._uid_cache_reverse(channel_uid)  # type: ignore[attr-defined]
        api_url = (
            f"{self.BASE_URL}/i/v2/channels/{channel_uid}"  # type: ignore[attr-defined]
            f"/products/{product_id}?withWindow=false"
        )

        logger.info(f"[NAVERSTORE] 상품 상세 조회: {product_id}")

        try:
            from curl_cffi.requests import AsyncSession

            # 쿠키가 있으면 프록시 불필요 (쿠키 자체가 인증 역할)
            proxies = None if cookies else self._build_proxies()  # type: ignore[attr-defined]
            async with AsyncSession(
                timeout=self._timeout,  # type: ignore[attr-defined]
                proxies=proxies,
                impersonate="chrome",
            ) as session:
                req_headers = {
                    **self.HEADERS,  # type: ignore[attr-defined]
                    "Referer": (
                        f"{self.BASE_URL}/{store_name}/products/{product_id}"  # type: ignore[attr-defined]
                        if store_name
                        else f"{self.BASE_URL}/"  # type: ignore[attr-defined]
                    ),
                }
                # 쿠키가 있으면 헤더에 추가 (확장앱에서 전달받은 브라우저 쿠키)
                if cookies:
                    req_headers["Cookie"] = cookies

                resp = await session.get(api_url, headers=req_headers)
                if resp.status_code != 200:
                    logger.warning(
                        f"[NAVERSTORE] 상품 상세 HTTP {resp.status_code}: {product_id}"
                    )
                    return {}

                data = resp.json()

            return self._transform_detail_product(data, channel_uid)

        except Exception as e:
            logger.error(f"[NAVERSTORE] 상품 상세 실패: {product_id} — {e}")
            return {}

    async def get_product_details_batch(
        self,
        product_ids: list[str],
        channel_uid: str,
        delay: float | None = None,
        on_progress: Any = None,
        cookies: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """상품 상세 배치 조회 — 429 방지를 위해 딜레이를 두고 순차 호출.

        Args:
            product_ids: 상품 ID 목록
            channel_uid: channelUid
            delay: 요청 간 딜레이 (초). None이면 DETAIL_DELAY 사용
            on_progress: 진행 콜백 (current, total)

        Returns:
            상품 상세 dict 목록
        """
        if delay is None:
            delay = self.DETAIL_DELAY  # type: ignore[attr-defined]

        results = []
        total = len(product_ids)
        store_name = self._uid_cache_reverse(channel_uid)  # type: ignore[attr-defined]

        # 쿠키가 있으면 프록시 불필요
        from curl_cffi.requests import AsyncSession

        proxies = None if cookies else self._build_proxies()  # type: ignore[attr-defined]
        async with AsyncSession(
            timeout=self._timeout,  # type: ignore[attr-defined]
            proxies=proxies,
            impersonate="chrome",
        ) as session:
            for idx, pid in enumerate(product_ids):
                if idx > 0:
                    await asyncio.sleep(delay)

                api_url = (
                    f"{self.BASE_URL}/i/v2/channels/{channel_uid}"  # type: ignore[attr-defined]
                    f"/products/{pid}?withWindow=false"
                )

                req_headers = {
                    **self.HEADERS,  # type: ignore[attr-defined]
                    "Referer": (
                        f"{self.BASE_URL}/{store_name}/products/{pid}"  # type: ignore[attr-defined]
                        if store_name
                        else f"{self.BASE_URL}/"  # type: ignore[attr-defined]
                    ),
                }
                # 쿠키가 있으면 헤더에 추가
                if cookies:
                    req_headers["Cookie"] = cookies

                try:
                    resp = await session.get(api_url, headers=req_headers)

                    if resp.status_code == 429:
                        logger.warning(
                            f"[NAVERSTORE] 429 감지 — {delay * 2:.1f}초 대기 후 재시도: {pid}"
                        )
                        await asyncio.sleep(delay * 2)
                        retry_headers = {
                            **self.HEADERS,  # type: ignore[attr-defined]
                            "Referer": f"{self.BASE_URL}/",  # type: ignore[attr-defined]
                        }
                        if cookies:
                            retry_headers["Cookie"] = cookies
                        resp = await session.get(api_url, headers=retry_headers)

                    if resp.status_code == 200:
                        data = resp.json()
                        detail = self._transform_detail_product(data, channel_uid)
                        results.append(detail)
                    else:
                        logger.warning(
                            f"[NAVERSTORE] 상세 HTTP {resp.status_code}: {pid}"
                        )

                except Exception as e:
                    logger.error(f"[NAVERSTORE] 상세 조회 실패: {pid} — {e}")

                if on_progress:
                    on_progress(idx + 1, total)

        logger.info(f"[NAVERSTORE] 배치 상세 조회 완료: {len(results)}/{total}개 성공")
        return results

    def _transform_detail_product(
        self, data: dict[str, Any], channel_uid: str
    ) -> dict[str, Any]:
        """상세 API 응답을 표준 상품 dict로 변환."""
        now_iso = datetime.now(tz=timezone.utc).isoformat()

        product_id = str(data.get("id", ""))
        product_no = str(data.get("productNo", ""))
        name = data.get("name") or data.get("dispName", "")
        sale_price = data.get("salePrice", 0)

        # 할인 정보
        benefits = data.get("benefitsView", {})
        if not benefits:
            policy = data.get("benefitsPolicy", {})
            discount_amount = policy.get("sellerImmediateDiscountValue", 0)
            discounted_price = (
                sale_price - discount_amount if discount_amount else sale_price
            )
            discount_rate = (
                round((1 - discounted_price / sale_price) * 100)
                if sale_price > discounted_price > 0
                else 0
            )
        else:
            discounted_price = benefits.get("discountedSalePrice", 0) or sale_price
            discount_rate = benefits.get("discountedRatio", 0)

        # 이미지
        representative_images = []
        optional_images = []
        for img in data.get("productImages", []):
            url = img.get("url", "")
            if not url:
                continue
            img_type = img.get("imageType", "")
            if img_type == "REPRESENTATIVE":
                representative_images.append(url)
            elif img_type == "OPTIONAL":
                optional_images.append(url)

        thumbnail = representative_images[0] if representative_images else ""

        # 카테고리
        category_info = data.get("category", {})
        category_str = ""
        if isinstance(category_info, dict):
            category_str = category_info.get("wholeCategoryName", "")

        # 브랜드/제조사
        search_info = data.get("naverShoppingSearchInfo", {})
        brand = search_info.get("brandName", "")
        manufacturer = search_info.get("manufacturerName", "")

        # 옵션 그룹 정의
        option_groups = []
        for opt in data.get("options", []):
            option_groups.append(
                {
                    "id": opt.get("id"),
                    "groupName": opt.get("groupName", ""),
                    "optionType": opt.get("optionType", ""),
                }
            )

        # 옵션 조합
        option_combinations = []
        for combo in data.get("optionCombinations", []):
            opt_names = {}
            for i in range(1, 4):
                key = f"optionName{i}"
                val = combo.get(key, "")
                if val:
                    group_name = (
                        option_groups[i - 1]["groupName"]
                        if i - 1 < len(option_groups)
                        else f"옵션{i}"
                    )
                    opt_names[group_name] = val

            display_name = " / ".join(opt_names.values())

            _combo_stock = _clamp_stock(combo.get("stockQuantity", 0))
            option_combinations.append(
                {
                    "id": combo.get("id"),
                    "names": opt_names,
                    "displayName": display_name,
                    "stockQuantity": _combo_stock,
                    "additionalPrice": combo.get("price", 0),
                    "isSoldOut": _combo_stock <= 0,
                    "todayDispatch": combo.get("todayDispatch", False),
                }
            )

        # 배송 정보
        delivery_info = data.get("productDeliveryInfo", {})
        delivery_company = delivery_info.get("deliveryCompany", {})
        delivery = {
            "deliveryFeeType": delivery_info.get("deliveryFeeType", ""),
            "baseFee": delivery_info.get("baseFee", 0),
            "deliveryCompany": (
                delivery_company.get("name", "")
                if isinstance(delivery_company, dict)
                else ""
            ),
            "area2ExtraFee": delivery_info.get("area2ExtraFee", 0),
            "area3ExtraFee": delivery_info.get("area3ExtraFee", 0),
            "freeDelivery": (delivery_info.get("deliveryFeeType", "") == "FREE"),
        }

        # 원산지
        origin_info = data.get("originAreaInfo", {})
        origin = origin_info.get("content", "") if isinstance(origin_info, dict) else ""

        # A/S 정보
        as_info = data.get("afterServiceInfo", {})

        # 상품정보고시 — 고시정보에서 세탁/취급 방법 추출
        product_notice = data.get("productInfoProvidedNoticeView", {})
        care_instructions = ""
        if product_notice:
            pairs: list[tuple[str, str]] = []

            def _collect_kv(obj: object, out: list[tuple[str, str]]) -> None:
                if isinstance(obj, list):
                    for item in obj:
                        _collect_kv(item, out)
                elif isinstance(obj, dict):
                    title = (
                        obj.get("title") or obj.get("name") or obj.get("label")  # type: ignore[union-attr]
                    )
                    content = (
                        obj.get("content") or obj.get("value") or obj.get("text")  # type: ignore[union-attr]
                    )
                    if isinstance(title, str) and isinstance(
                        content, (str, int, float)
                    ):
                        out.append((title, str(content)))
                        return
                    for _k, _v in obj.items():  # type: ignore[union-attr]
                        if isinstance(_v, (dict, list)):
                            _collect_kv(_v, out)
                        elif isinstance(_v, (str, int, float)):
                            out.append((str(_k), str(_v)))

            _collect_kv(product_notice, pairs)
            for _pk, _pv in pairs:
                _pk_low = str(_pk).lower()
                _pv_str = str(_pv).strip() if _pv else ""
                if not _pv_str or _pv_str in (
                    "해당없음",
                    "상세설명참조",
                    "상세페이지참조",
                ):
                    continue
                if any(kw in _pk_low for kw in ("세탁", "취급", "care", "wash")):
                    care_instructions = _pv_str
                    break

        # 채널 정보
        channel = data.get("channel", {})
        store_name = channel.get("channelName", "")
        store_url_path = channel.get("channelSiteUrl", "")

        # 판매상태
        status_type = data.get("productStatusType", "")
        _main_stock = _clamp_stock(data.get("stockQuantity", 0))
        is_sold_out = status_type != "SALE" or _main_stock <= 0

        # 셀러 관리코드
        seller_code = data.get("sellerCodeInfo", {}).get("sellerManagementCode", "")

        # 태그
        tags = []
        seo = data.get("seoInfo", {})
        if isinstance(seo, dict):
            for tag in seo.get("sellerTags", []):
                text = tag.get("text", "")
                if text:
                    tags.append(text)

        return {
            "siteProductId": product_id,
            "productNo": product_no,
            "name": name,
            "brand": brand,
            "manufacturer": manufacturer,
            "originalPrice": sale_price,
            "salePrice": discounted_price,
            "discountRate": discount_rate,
            "stockQuantity": _main_stock,
            "thumbnailImageUrl": thumbnail,
            "images": representative_images + optional_images,
            "representativeImages": representative_images,
            "optionalImages": optional_images,
            "category": category_str,
            "categoryId": category_info.get("categoryId", ""),
            "optionGroups": option_groups,
            "optionCombinations": option_combinations,
            "optionUsable": data.get("optionUsable", False),
            "delivery": delivery,
            "origin": origin,
            "care_instructions": care_instructions,
            "afterServiceInfo": {
                "telephone": as_info.get("afterServiceTelephoneNumber", ""),
                "guide": as_info.get("afterServiceGuideContent", ""),
            },
            "productInfoNotice": product_notice,
            "tags": tags,
            "sellerCode": seller_code,
            "storeName": store_name,
            "storeUrlPath": store_url_path,
            "channelUid": channel_uid,
            "isSoldOut": is_sold_out,
            "sourceSite": "NAVERSTORE",
            "sourceUrl": (f"{self.BASE_URL}/{store_url_path}/products/{product_id}"),  # type: ignore[attr-defined]
            "collectedAt": now_iso,
            "updatedAt": now_iso,
        }
