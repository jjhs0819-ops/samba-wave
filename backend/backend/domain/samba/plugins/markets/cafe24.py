"""카페24 마켓 플러그인 — OAuth2 기반 상품 등록/수정/삭제.

카페24 Admin REST API v2 사용.
인증: OAuth2 (access_token + refresh_token)
상품 등록 플로우:
  1. 상품 생성 (POST /products)
  2. 이미지 URL 설정 (PUT /products/{no})
  3. 카테고리 연결 (POST /categories/products)
  4. 옵션 등록 (POST /products/{no}/options)
  5. 품목(variant)별 재고 설정 (PUT /products/{no}/variants/{code})
"""

from __future__ import annotations

import time as _time_mod
from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.utils.logger import logger

# 배치 내 중복 등록 방지 — {custom_code: (product_no, timestamp)}
_registered_cache: dict[str, tuple[int, float]] = {}
_CACHE_TTL = 600  # 10분간 유지

# 소싱처별 이미지 CDN 허용 도메인 — 브랜드 광고/사이즈/안내 이미지 차단용 화이트리스트
# (무신사 등록 방식 기준 — 다른 소싱처도 동일 패턴 적용)
_ALLOWED_IMAGE_HOSTS: tuple[str, ...] = (
    "msscdn.net",  # 무신사
    "kream.co.kr",  # KREAM
    "fashionplus",  # 패션플러스
    "nike.com",  # 나이키 (static.nike.com 등)
    "a-rt.com",  # ABC마트
    "ssgcdn.com",  # 신세계몰
    "lotteimall.com",  # 롯데ON
    "gsshop.com",  # GS샵
    "pstatic.net",  # 네이버스토어, KREAM (shop-phinf, shopping-phinf)
)


def _is_allowed_image(url: str) -> bool:
    """등록 허용 CDN 도메인인지 확인."""
    if not url:
        return False
    return any(host in url for host in _ALLOWED_IMAGE_HOSTS)


class Cafe24Plugin(MarketPlugin):
    """카페24 마켓 플러그인.

    자사몰 솔루션 — 카페24 API를 통해 상품 등록/수정/삭제.
    """

    market_type = "cafe24"
    policy_key = "카페24"
    required_fields = ["name", "sale_price"]

    async def handle(
        self,
        session,
        product: dict,
        category_id: str,
        account=None,
        existing_no: str = "",
    ) -> dict[str, Any]:
        """카테고리 없어도 execute() 진행 — 자동 생성 지원."""
        creds = await self._load_auth(session, account)
        if not creds:
            return {"success": False, "message": "카페24 인증정보 없음"}
        product = await self._apply_market_settings(session, product, account)
        try:
            return await self.execute(
                session, product, creds, category_id or "", account, existing_no
            )
        except Exception as e:
            # invalid_grant: 병렬 요청 중 토큰이 갱신됐을 수 있음 → DB에서 최신 토큰 재로드 후 1회 재시도
            if "invalid_grant" in str(e) or "invalid_token" in str(e):
                import asyncio as _aio

                logger.warning("[카페24] invalid_grant 감지 → 토큰 재로드 후 재시도")
                await _aio.sleep(0.5)
                fresh_creds = await self._load_auth(session, account)
                if fresh_creds:
                    try:
                        return await self.execute(
                            session,
                            product,
                            fresh_creds,
                            category_id or "",
                            account,
                            existing_no,
                        )
                    except Exception as retry_e:
                        return {
                            "success": False,
                            "error_type": self._classify_error(retry_e),
                            "message": str(retry_e),
                        }
            return {
                "success": False,
                "error_type": self._classify_error(e),
                "message": str(e),
            }

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        from backend.domain.samba.proxy.cafe24 import Cafe24Client

        return Cafe24Client.transform_product(product, category_id)

    async def execute(
        self,
        session,
        product: dict,
        creds: dict,
        category_id: str,
        account,
        existing_no: str,
    ) -> dict[str, Any]:
        """카페24 상품 등록/수정."""
        import time as _time_c24

        from backend.domain.samba.proxy.cafe24 import Cafe24Client

        _t_start = _time_c24.monotonic()
        _t_prev = _t_start

        def _tick(label: str) -> None:
            nonlocal _t_prev
            _now = _time_c24.monotonic()
            logger.info(
                f"[카페24][타이밍] {label}: Δ{(_now - _t_prev) * 1000:.0f}ms "
                f"(누적 {(_now - _t_start) * 1000:.0f}ms)"
            )
            _t_prev = _now

        # 인증정보 추출
        mall_id = (
            creds.get("mallId")
            or creds.get("storeId")
            or (account.seller_id if account else "")
            or ""
        )
        client_id = creds.get("clientId", "")
        client_secret = creds.get("clientSecret", "")
        access_token = creds.get("accessToken", "")
        refresh_token = creds.get("refreshToken", "")

        if not mall_id:
            return {
                "success": False,
                "message": "카페24 Mall ID가 없습니다. 계정 설정에서 mallId를 입력해주세요.",
            }
        if not client_id or not client_secret:
            return {
                "success": False,
                "message": "카페24 Client ID/Secret이 없습니다. 계정 설정에서 입력해주세요.",
            }
        if not access_token and not refresh_token:
            return {
                "success": False,
                "message": "카페24 Access Token 또는 Refresh Token이 없습니다.",
            }

        client = Cafe24Client(
            mall_id=mall_id,
            client_id=client_id,
            client_secret=client_secret,
            access_token=access_token,
            refresh_token=refresh_token,
        )
        _tick("init")

        # 중복 등록 방지용 custom_code 미리 계산
        _custom_code = (product.get("source_product_id") or product.get("id", ""))[:40]

        # 중복 등록 방지 1단계: market_product_nos 체크
        if not existing_no and account:
            _m_nos = product.get("market_product_nos") or {}
            _existing = _m_nos.get(account.id) or _m_nos.get(str(account.id))
            if _existing:
                existing_no = str(_existing)
                logger.info(
                    f"[카페24][중복방지] DB product_no={existing_no} 발견 → 수정 모드 전환"
                )

        # 중복 등록 방지 2단계: 메모리 캐시 체크 (같은 배치 내 중복 차단)
        if not existing_no and _custom_code:
            _cached = _registered_cache.get(_custom_code)
            if _cached and (_time_mod.time() - _cached[1]) < _CACHE_TTL:
                existing_no = str(_cached[0])
                logger.info(
                    f"[카페24][중복방지] 캐시 product_no={existing_no} 발견 → 수정 모드 전환"
                )

        # 중복 등록 방지 3단계: 카페24 API에서 custom_product_code로 기존 상품 검색
        if not existing_no and _custom_code:
            _found_no = await client.find_product_by_custom_code(_custom_code)
            if _found_no:
                existing_no = str(_found_no)
                logger.info(
                    f"[카페24][중복방지] API 검색 product_no={existing_no} 발견 → 수정 모드 전환"
                )

        # 계정 설정 주입
        product_copy = dict(product)
        if account:
            extras = account.additional_fields or {}
            if extras.get("asPhone"):
                product_copy["_as_phone"] = extras["asPhone"]

        # 정책에서 배송비/재고 설정 + 상세페이지 템플릿 로드
        policy_id = product.get("applied_policy_id")
        _detail_tpl_top_key = ""
        _detail_tpl_bottom_key = ""
        if policy_id:
            from backend.domain.samba.policy.repository import SambaPolicyRepository

            policy_repo = SambaPolicyRepository(session)
            _policy = await policy_repo.get_async(policy_id)
            if _policy:
                pr = _policy.pricing or {}
                mp: dict[str, Any] = (_policy.market_policies or {}).get("카페24", {})
                shipping = int(mp.get("shippingCost") or pr.get("shippingCost") or 0)
                if shipping > 0:
                    product_copy["_delivery_fee_type"] = "PAID"
                    product_copy["_delivery_base_fee"] = shipping
                max_stock_val = mp.get("maxStock")
                if max_stock_val:
                    product_copy["_max_stock"] = max_stock_val
                shipping_days = int(mp.get("shippingDays") or 3)
                product_copy["_shipping_days"] = shipping_days

                # 상세페이지 템플릿 조회 — policy.extras.detail_template_id
                _extras = _policy.extras or {}
                _tpl_id = _extras.get("detail_template_id")
                if _tpl_id:
                    try:
                        from backend.domain.samba.policy.model import (
                            SambaDetailTemplate,
                        )
                        from backend.domain.shared.base_repository import BaseRepository

                        _tpl_repo = BaseRepository(session, SambaDetailTemplate)
                        _tpl = await _tpl_repo.get_async(_tpl_id)
                        if _tpl:
                            _detail_tpl_top_key = _tpl.top_image_s3_key or ""
                            _detail_tpl_bottom_key = _tpl.bottom_image_s3_key or ""
                            logger.info(
                                f"[카페24] 상세 템플릿 로드 완료 — 상단:{bool(_detail_tpl_top_key)}, 하단:{bool(_detail_tpl_bottom_key)}"
                            )
                        else:
                            logger.warning(f"[카페24] 상세 템플릿 {_tpl_id} 조회 실패")
                    except Exception as _tpl_e:
                        logger.warning(
                            f"[카페24] 상세 템플릿 로드 예외 (무시): {_tpl_e}"
                        )
        _tick("policy+template")

        # 카테고리 유효성 확인 — 카페24 전체 카테고리 1회 조회 (자동생성 시에도 재사용)
        all_cats = await client.get_categories()
        _tick("get_categories")
        existing_nos = {int(c.get("category_no", 0)) for c in all_cats}
        if (
            category_id
            and str(category_id).isdigit()
            and int(category_id) not in existing_nos
        ):
            logger.warning(
                f"[카페24] 카테고리 {category_id} 존재하지 않음 → 자동 생성으로 전환"
            )
            category_id = ""

        # category_id가 없거나 숫자가 아니면 소싱처 카테고리로 자동 생성
        if not category_id or not str(category_id).isdigit():
            cat_levels = [
                product_copy.get("category1") or "",
                product_copy.get("category2") or "",
                product_copy.get("category3") or "",
                product_copy.get("category4") or "",
            ]
            cat_levels = [c.strip() for c in cat_levels if c and c.strip()]
            if cat_levels:
                _sex = product_copy.get("sex") or ""
                normalized = Cafe24Plugin._normalize_category(cat_levels, sex=_sex)
                _levels = normalized if normalized else cat_levels[:4]
                # 연속된 동일 레벨명 제거 (예: 러닝화>러닝화 방지)
                use_levels: list[str] = []
                for _lv in _levels:
                    if not use_levels or use_levels[-1] != _lv:
                        use_levels.append(_lv)
                auto_no = await client.get_or_create_category_chain(
                    use_levels, existing_cats=all_cats
                )
                if auto_no:
                    category_id = str(auto_no)
                    logger.info(
                        f"[카페24] 카테고리 자동 매핑: {' > '.join(cat_levels)} → {' > '.join(use_levels)} (no={category_id})"
                    )

        _tick("category_map")

        # 제조사/브랜드 자동 생성 후 코드 조회 — 병렬
        _brand = product_copy.get("brand") or ""
        _manufacturer = product_copy.get("manufacturer") or _brand
        logger.info(
            f"[카페24][제조사진단] product='{product_copy.get('name', '')[:30]}' "
            f"| manufacturer원본={product_copy.get('manufacturer')!r} "
            f"| brand={_brand!r} | 최종사용값={_manufacturer!r}"
        )
        manufacturer_code = None
        brand_code = None
        import asyncio as _aio_c24

        _mfr_task = (
            client.get_or_create_manufacturer(_manufacturer) if _manufacturer else None
        )
        _brand_task = client.get_or_create_brand(_brand) if _brand else None
        if _mfr_task and _brand_task:
            manufacturer_code, brand_code = await _aio_c24.gather(
                _mfr_task, _brand_task
            )
        elif _mfr_task:
            manufacturer_code = await _mfr_task
        elif _brand_task:
            brand_code = await _brand_task
        _tick("manufacturer+brand")

        # 카페24 상세페이지: 상하단 템플릿 + 대표이미지 + 추가이미지만
        # 소싱처 CDN 화이트리스트 이미지만 허용 — 브랜드 광고/사이즈/안내 이미지 차단
        _img_tag = '<div style="text-align:center;"><img src="{url}" style="max-width:100%;height:auto;display:block;margin:0 auto;" /></div>'

        # 상/하단 HTML: 정책 상세 템플릿 > product_copy 오버라이드 순 fallback
        def _extract_img_url(value: str) -> str:
            """img 태그가 저장된 경우 src URL만 추출."""
            if not value:
                return ""
            _v = value.strip()
            if _v.startswith("<img"):
                import re as _re

                m = _re.search(r'src=["\']([^"\']+)["\']', _v)
                return m.group(1) if m else ""
            return _v

        _top = product_copy.get("_detail_top_html", "")
        _bottom = product_copy.get("_detail_bottom_html", "")
        if not _top and _detail_tpl_top_key:
            _top_url = _extract_img_url(_detail_tpl_top_key)
            if _top_url:
                _top = _img_tag.format(url=_top_url)
        if not _bottom and _detail_tpl_bottom_key:
            _bottom_url = _extract_img_url(_detail_tpl_bottom_key)
            if _bottom_url:
                _bottom = _img_tag.format(url=_bottom_url)
        # 대표이미지 1장 + 추가이미지 최대 5장만 사용, 나머지 버림
        # collector가 부족분을 detail_images로 보충하므로(brand 배너 포함) 제외
        _detail_set = set(product_copy.get("detail_images") or [])
        _clean_images = [
            u
            for u in (product_copy.get("images") or [])
            if _is_allowed_image(u) and u not in _detail_set
        ][:6]
        # images 배열이 비어있으면 대표이미지(images[0])로 fallback
        # — detail_images와 중복되어 필터에서 제외된 경우 대응 (네이버스토어 등)
        if not _clean_images:
            _all_images = product_copy.get("images") or []
            for _u in _all_images:
                if _u and _is_allowed_image(_u):
                    _clean_images = [_u]
                    logger.info(
                        f"[카페24] 상세페이지 대표이미지 fallback(images[0]): {_u[:80]}"
                    )
                    break
        _imgs = [_img_tag.format(url=u) for u in _clean_images]
        # 전체 상세페이지를 760px 박스로 감싸 템플릿+상품이미지 통일
        _inner = "\n".join(p for p in [_top] + _imgs + [_bottom] if p)
        product_copy["detail_html"] = (
            '<div style="max-width:760px;margin:0 auto;">' + _inner + "</div>"
        )

        # 디버그: detail_html 구성 내역 로깅
        _pname = product_copy.get("name", "")[:30]
        logger.info(
            f"[카페24][디버그] '{_pname}' — images={len(_imgs)}개 "
            f"| top_html={len(_top)}bytes | bottom_html={len(_bottom)}bytes "
            f"| detail_html총={len(product_copy['detail_html'])}bytes"
        )
        if _top:
            logger.info(f"[카페24][디버그] _detail_top_html 앞200자: {_top[:200]}")
        if _bottom:
            logger.info(
                f"[카페24][디버그] _detail_bottom_html 앞200자: {_bottom[:200]}"
            )
        if product_copy["detail_html"]:
            logger.info(
                f"[카페24][디버그] detail_html 앞500자: {product_copy['detail_html'][:500]}"
            )

        # 제조사/브랜드 코드 상품 데이터에 주입
        if manufacturer_code:
            product_copy["_manufacturer_code"] = manufacturer_code
        if brand_code:
            product_copy["_brand_code"] = brand_code

        # 상품 데이터 변환
        data = Cafe24Client.transform_product(product_copy, category_id)
        _tick("transform")

        # ── 상품 수정 모드 ──
        if existing_no:
            try:
                product_no = int(existing_no)
                result = await client.update_product(product_no, data)
                _tick("update_product")

                # 토큰 갱신됐으면 저장 (실패해도 등록 성공에 영향 없어야 함)
                try:
                    await self._save_tokens_if_changed(session, account, client)
                except Exception as tok_e:
                    logger.warning(f"[카페24] 토큰 저장 중 예외 (무시): {tok_e}")

                return {
                    "success": True,
                    "message": "카페24 수정 성공",
                    "data": {"productNo": product_no, **result},
                }
            except Exception as e:
                err_msg = str(e)
                if "404" in err_msg:
                    logger.warning(f"[카페24] 상품 {existing_no} 없음 → 신규등록 전환")
                    # 신규등록으로 전환
                else:
                    return {"success": False, "message": f"카페24 수정 실패: {err_msg}"}

        # ── 상품 신규등록 ──
        try:
            # 옵션 데이터 사전 계산 (등록 payload에 포함 필요)
            options = product_copy.get("options") or []
            sale_price = int(product_copy.get("sale_price", 0) or 0)
            max_stock = product_copy.get("_max_stock", 0)
            opt_payload = (
                Cafe24Client.build_options_payload(options, sale_price, max_stock)
                if options
                else None
            )

            # 옵션이 있으면 초기 등록 payload에 포함 (option_type:S 필수)
            if opt_payload:
                data["request"]["has_option"] = "T"
                data["request"]["option_type"] = "S"
                data["request"]["options"] = [
                    {
                        "name": o["name"],
                        "value": o["values"],
                    }
                    for o in opt_payload
                ]

            # 1. 상품 생성 (옵션 포함)
            result = await client.register_product(data)
            product_no = result.get("product_no")
            if not product_no:
                return {
                    "success": False,
                    "message": "카페24 상품 생성 실패: product_no 없음",
                }

            logger.info(f"[카페24] 1단계 완료 — 상품 생성: product_no={product_no}")
            # 캐시에 등록 (같은 배치 내 중복 방지)
            if _custom_code:
                _registered_cache[_custom_code] = (product_no, _time_mod.time())
            _tick("register_product")

            # ═══ 병렬 실행 영역 시작 ═══
            # origin/SEO/image/variant는 모두 register 이후 독립 작업이므로 병렬 처리
            import asyncio as _aio_run

            _parallel_tasks: list = []

            # 1-1. 원산지 별도 PUT (POST /products는 origin 무시 — 별도 업데이트 필요)
            # API 형식: origin_classification(F=국내/T=해외/E=기타) + made_in_code(ISO 2자리)
            origin_text = (product_copy.get("origin") or "").strip()
            origin_payload: dict | None = None
            if origin_text:
                try:
                    # origin_place_no: 카페24 내부 원산지 코드 (어드민 HTML 드롭다운 확인값)
                    # F=국내, T=해외(place_no 필요), E=기타(텍스트)
                    _ORIGIN_PLACE_MAP: dict[str, tuple[str, int | None]] = {
                        # 국내
                        "한국": ("F", None),
                        "대한민국": ("F", None),
                        # 아시아
                        "그루지야": ("T", 232),
                        "네팔": ("T", 233),
                        "동티모르": ("T", 234),
                        "라오스": ("T", 235),
                        "레바논": ("T", 236),
                        "말레이시아": ("T", 237),
                        "몽골": ("T", 239),
                        "미얀마": ("T", 240),
                        "바레인": ("T", 241),
                        "방글라데시": ("T", 242),
                        "베트남": ("T", 243),
                        "부탄": ("T", 244),
                        "북한": ("T", 245),
                        "브루나이": ("T", 246),
                        "사우디아라비아": ("T", 247),
                        "스리랑카": ("T", 248),
                        "싱가포르": ("T", 250),
                        "아랍에미리트": ("T", 251),
                        "인도": ("T", 261),
                        "인도네시아": ("T", 262),
                        "일본": ("T", 263),
                        "중국": ("T", 264),
                        "캄보디아": ("T", 267),
                        "태국": ("T", 270),
                        "파키스탄": ("T", 272),
                        "필리핀": ("T", 273),
                        "대만": ("T", 1811),
                        "홍콩": ("T", 2551),
                        "마카오": ("T", 2555),
                        # 유럽
                        "그리스": ("T", 316),
                        "네덜란드": ("T", 317),
                        "노르웨이": ("T", 318),
                        "덴마크": ("T", 319),
                        "독일": ("T", 320),
                        "러시아": ("T", 322),
                        "벨기에": ("T", 330),
                        "스웨덴": ("T", 334),
                        "스위스": ("T", 335),
                        "스페인": ("T", 336),
                        "영국": ("T", 345),
                        "오스트리아": ("T", 346),
                        "이탈리아": ("T", 348),
                        "체코": ("T", 349),
                        "터키": ("T", 352),
                        "포르투갈": ("T", 353),
                        "폴란드": ("T", 354),
                        "프랑스": ("T", 355),
                        "핀란드": ("T", 356),
                        "헝가리": ("T", 357),
                        "우크라이나": ("T", 2585),
                        # 아메리카
                        "미국": ("T", 358),
                        "캐나다": ("T", 361),
                        "멕시코": ("T", 366),
                        "브라질": ("T", 370),
                        "아르헨티나": ("T", 373),
                        "칠레": ("T", 379),
                        "콜롬비아": ("T", 381),
                        "페루": ("T", 385),
                        # 오세아니아
                        "뉴질랜드": ("T", 388),
                        "호주": ("T", 399),
                        "파푸아뉴기니": ("T", 396),
                        "피지": ("T", 398),
                        # 아프리카
                        "가나": ("T", 274),
                        "나이지리아": ("T", 278),
                        "남아프리카공화국": ("T", 279),
                        "남아공": ("T", 279),
                        "모로코": ("T", 287),
                        "에디오피아": ("T", 297),
                        "이집트": ("T", 299),
                        "케냐": ("T", 308),
                        "탄자니아": ("T", 313),
                        "튀니지": ("T", 315),
                        "알제리": ("T", 294),
                        "앙골라": ("T", 295),
                    }
                    classification, place_no = _ORIGIN_PLACE_MAP.get(
                        origin_text, ("E", None)
                    )
                    if classification == "T" and place_no:
                        origin_payload = {
                            "origin_classification": "T",
                            "origin_place_no": place_no,
                        }
                    elif classification == "F":
                        origin_payload = {"origin_classification": "F"}
                    else:
                        origin_payload = {
                            "origin_classification": "E",
                            "origin_place_value": origin_text[:30],
                        }
                except Exception as e:
                    logger.warning(f"[카페24] 원산지 payload 구성 실패 (무시): {e}")

            async def _do_origin() -> None:
                if not origin_payload:
                    return
                try:
                    await client.update_product(
                        product_no,
                        {"shop_no": 1, "request": origin_payload},
                    )
                    logger.info(
                        f"[카페24] 원산지 설정 완료: '{origin_text}' → {origin_payload}"
                    )
                except Exception as e:
                    logger.warning(f"[카페24] 원산지 설정 실패 (무시): {e}")

            if origin_payload:
                _parallel_tasks.append(_do_origin())

            # 1-2. SEO 설정 (스마트스토어 태그 로직 참고)
            product_name = product_copy.get("name") or product_copy.get("title") or ""
            brand_name = product_copy.get("brand") or ""
            tags = product_copy.get("tags") or []
            # 브랜드명·상품명 포함 태그 제외, 최대 10개 (스마트스토어 방식 참고)
            brand_lower = brand_name.lower()
            name_lower = product_name.lower()
            kw_list: list[str] = []
            seen: set[str] = set()
            for t in tags:
                if not t or t.startswith("__"):
                    continue
                tl = t.lower().replace(" ", "")
                if tl in seen:
                    continue
                seen.add(tl)
                if brand_lower and brand_lower in t.lower():
                    continue
                if t.lower() in name_lower:
                    continue
                kw_list.append(t)
                if len(kw_list) >= 10:
                    break
            # 브랜드명은 맨 앞에 추가
            if brand_name:
                kw_list.insert(0, brand_name)
            keywords = ", ".join(kw_list) if kw_list else product_name

            async def _do_seo() -> None:
                try:
                    await client.update_product_seo(
                        product_no,
                        {
                            "shop_no": 1,
                            "request": {
                                "search_engine_exposure": "T",
                                "meta_title": product_name,
                                "meta_description": product_name,
                                "meta_keywords": keywords,
                                "meta_alt": product_name,
                            },
                        },
                    )
                    logger.info(f"[카페24] SEO 설정 완료: keywords={keywords[:50]}")
                except Exception as e:
                    logger.warning(f"[카페24] SEO 설정 실패 (무시): {e}")

            _parallel_tasks.append(_do_seo())

            # 2. 이미지 업로드 (대표이미지 — POST /products는 이미지 필드 무시됨)
            # 소싱처 CDN 화이트리스트 이미지만 허용 — 브랜드 광고/사이즈/안내 이미지 차단
            images = [
                u for u in (product_copy.get("images") or []) if _is_allowed_image(u)
            ]

            async def _do_images() -> None:
                if not images:
                    return
                try:
                    await client.upload_images(product_no, images)
                    logger.info(f"[카페24] 2단계 완료 — 이미지 업로드: {len(images)}개")
                except Exception as img_e:
                    logger.warning(f"[카페24] 이미지 업로드 실패 (무시): {img_e}")

            if images:
                _parallel_tasks.append(_do_images())

            # 카테고리는 POST /products의 add_category_no로 이미 설정됨 (별도 연결 불필요)

            # 3. variant 재고 설정 — 다른 병렬 작업과 함께 실행
            async def _do_variants() -> None:
                if not opt_payload:
                    return
                try:
                    logger.info(
                        "[카페24] 3단계 — 옵션 포함 등록 완료, variant 재고 설정 시작"
                    )
                    await _aio_run.sleep(0.3)  # variant 생성 대기
                    variants = await client.get_variants(product_no)
                    if not variants:
                        return
                    logger.info(
                        f"[카페24][재고디버그] variant 샘플 원본: {variants[0]}"
                    )
                    for _o in options:
                        logger.info(
                            f"[카페24][재고디버그] 옵션 name={_o.get('name')} "
                            f"stock={_o.get('stock')} isSoldOut={_o.get('isSoldOut')}"
                        )
                    updates = Cafe24Client.build_variant_updates(
                        options,
                        variants,
                        sale_price,
                        max_stock,
                    )
                    for _u in updates:
                        logger.info(f"[카페24][재고디버그] variant 업데이트: {_u}")

                    async def _update_variant(upd: dict) -> None:
                        vcode = upd.pop("variant_code")
                        try:
                            await client.update_variant(product_no, vcode, upd)
                        except Exception as var_e:
                            logger.warning(
                                f"[카페24] variant {vcode} 업데이트 실패: {var_e}"
                            )

                    await _aio_run.gather(*[_update_variant(upd) for upd in updates])
                    logger.info(
                        f"[카페24] 4단계 완료 — variant 재고 설정: {len(updates)}개 (병렬)"
                    )
                except Exception as opt_e:
                    logger.warning(f"[카페24] 옵션 등록 실패 (무시): {opt_e}")

            if opt_payload:
                _parallel_tasks.append(_do_variants())

            # ═══ 병렬 실행 ═══ origin/SEO/image/variant 동시 실행
            if _parallel_tasks:
                await _aio_run.gather(*_parallel_tasks, return_exceptions=True)
                _tick(f"parallel({len(_parallel_tasks)})")

            # 토큰 갱신됐으면 저장 (실패해도 등록 성공에 영향 없어야 함)
            try:
                await self._save_tokens_if_changed(session, account, client)
            except Exception as tok_e:
                logger.warning(f"[카페24] 토큰 저장 중 예외 (무시): {tok_e}")

            return {
                "success": True,
                "message": "카페24 등록 성공",
                "data": {"product_no": product_no, "productNo": product_no, **result},
            }

        except Exception as e:
            return {"success": False, "message": f"카페24 등록 실패: {e}"}

    async def delete(self, session, product_no: str, account) -> dict[str, Any]:
        """카페24 상품 완전 삭제 (마켓삭제).

        CLAUDE.md 규칙: "삭제"는 마켓에서 상품을 완전히 삭제하는 것(마켓삭제)이며,
        판매중지(SUSPENSION/STOP)와는 다른 개념이다.
        """
        creds = await self._load_auth(session, account)
        if not creds:
            return {"success": False, "message": "카페24 인증정보 없음"}

        from backend.domain.samba.proxy.cafe24 import Cafe24Client

        _mall_id = (
            creds.get("mallId")
            or creds.get("storeId")
            or (account.seller_id if account else "")
            or ""
        )
        client = Cafe24Client(
            mall_id=_mall_id,
            client_id=creds.get("clientId", ""),
            client_secret=creds.get("clientSecret", ""),
            access_token=creds.get("accessToken", ""),
            refresh_token=creds.get("refreshToken", ""),
        )

        try:
            await client.delete_product(int(product_no))
            # 토큰 갱신됐으면 저장 (실패해도 삭제 성공에 영향 없어야 함)
            try:
                await self._save_tokens_if_changed(session, account, client)
            except Exception as tok_e:
                logger.warning(f"[카페24] 토큰 저장 중 예외 (무시): {tok_e}")
            return {"success": True, "message": "카페24 상품 삭제 완료"}
        except Exception as e:
            err_msg = str(e)
            # 이미 삭제된 상품(404)은 성공으로 처리
            if "404" in err_msg:
                return {"success": True, "message": "카페24 상품 이미 삭제됨"}
            return {"success": False, "message": f"카페24 삭제 실패: {err_msg}"}

    async def test_auth(self, session, account) -> bool:
        """카페24 인증 테스트 — 카테고리 조회로 확인."""
        creds = await self._load_auth(session, account)
        if not creds:
            return False

        from backend.domain.samba.proxy.cafe24 import Cafe24Client

        _mall_id = (
            creds.get("mallId")
            or creds.get("storeId")
            or (account.seller_id if account else "")
            or ""
        )
        client = Cafe24Client(
            mall_id=_mall_id,
            client_id=creds.get("clientId", ""),
            client_secret=creds.get("clientSecret", ""),
            access_token=creds.get("accessToken", ""),
            refresh_token=creds.get("refreshToken", ""),
        )
        try:
            cats = await client.get_categories()
            logger.info(f"[카페24] 인증 테스트 성공: {len(cats)}개 카테고리")
            return True
        except Exception as e:
            logger.warning(f"[카페24] 인증 테스트 실패: {e}")
            return False

    @staticmethod
    def _normalize_category(cat_levels: list[str], sex: str = "") -> list[str]:
        """소싱처 카테고리 키워드 → 카페24 카테고리 트리 정규화.

        대분류: 의류, 신발, 가방, ETC, 뷰티, 스포츠/레저, 키즈, 속옷/홈웨어
        의류는 4단계: [대분류, 성별, 소분류, 세분류]
        기타는 3단계: [대분류, 중분류, 소분류]
        """
        if not cat_levels:
            return []

        text = " ".join(cat_levels)

        # ── 성별 판정 (의류/키즈 분류에 사용) ──
        _g = (sex or "").strip().lower()
        _is_female = any(
            k in text for k in ["여성", "여자", "우먼", "women", "wmns", "wns"]
        ) or _g in ("여성", "여", "female", "f")
        _is_male = any(
            k in text for k in ["남성", "남자", "맨즈", "men", "mens"]
        ) or _g in ("남성", "남", "male", "m")
        if _is_female and not _is_male:
            _clothing_gender = "여성의류"
            _kids_gender = "여아의류"
        elif _is_male and not _is_female:
            _clothing_gender = "남성의류"
            _kids_gender = "남아의류"
        else:
            _clothing_gender = "남여공용"
            _kids_gender = "남아의류"  # 키즈는 공용 없음, 남아 디폴트

        # ── 키즈/아동 우선 분기 ──
        if any(
            k in text
            for k in [
                "아동",
                "유아",
                "키즈",
                "kids",
                "베이비",
                "영아",
                "초등",
                "주니어",
            ]
        ):
            # 소싱처 3번째 레벨 활용 (예: 키즈 > 상의 > 반소매 티셔츠)
            _kids_sub = cat_levels[2] if len(cat_levels) >= 3 else ""
            # 의류 계열 → 키즈 > 소분류 > 세분류 (성별 구분 없음)
            if any(
                k in text for k in ["아우터", "점퍼", "재킷", "자켓", "코트", "패딩"]
            ):
                return (
                    ["키즈", "아우터", _kids_sub] if _kids_sub else ["키즈", "아우터"]
                )
            if any(k in text for k in ["바지", "팬츠", "하의"]):
                return ["키즈", "하의", _kids_sub] if _kids_sub else ["키즈", "하의"]
            if any(k in text for k in ["상의", "티셔츠", "셔츠", "니트"]):
                return ["키즈", "상의", _kids_sub] if _kids_sub else ["키즈", "상의"]
            if any(k in text for k in ["원피스", "드레스"]):
                return (
                    ["키즈", "원피스", _kids_sub] if _kids_sub else ["키즈", "원피스"]
                )
            if any(k in text for k in ["스커트", "치마"]):
                return (
                    ["키즈", "스커트", _kids_sub] if _kids_sub else ["키즈", "스커트"]
                )
            # ETC 계열 → 키즈 > ETC > 소분류
            if any(k in text for k in ["모자", "캡", "비니"]):
                return ["키즈", "ETC", "모자"]
            if any(k in text for k in ["가방", "백팩", "파우치"]):
                return ["키즈", "ETC", "가방"]
            if any(k in text for k in ["주얼리", "귀걸이", "목걸이", "팔찌", "반지"]):
                return ["키즈", "ETC", "주얼리"]
            if any(k in text for k in ["시계", "워치"]):
                return ["키즈", "ETC", "시계"]
            if any(k in text for k in ["양말", "삭스"]):
                return ["키즈", "ETC", "양말"]
            if any(k in text for k in ["머플러", "스카프", "넥워머"]):
                return ["키즈", "ETC", "머플러"]
            if "벨트" in text:
                return ["키즈", "ETC", "벨트"]
            if any(k in text for k in ["신발", "슈즈"]):
                return ["키즈", "ETC", "신발"]
            if any(k in text for k in ["액세서리", "소품"]):
                return ["키즈", "ETC", "액세서리"]
            return ["키즈", "상의"]

        # ── 스포츠/레저 → 대분류 없이 기존 카테고리로 분기 ──
        if any(
            k in text
            for k in [
                "스포츠",
                "레저",
                "골프",
                "요가",
                "필라테스",
                "수영복",
                "비치웨어",
                "등산",
                "아웃도어",
                "트레킹",
                "테니스",
                "운동복",
                "헬스",
            ]
        ):
            if any(k in text for k in ["수영복", "비치웨어", "비치", "비키니"]):
                _swim_gender = (
                    "여성수영복/비치웨어" if _is_female else "남성수영복/비치웨어"
                )
                _swim_sub = cat_levels[-1] if len(cat_levels) >= 2 else ""
                if _swim_sub:
                    return ["스포츠/레저", _swim_gender, _swim_sub]
                return ["스포츠/레저", _swim_gender, "수영복"]
            if any(
                k in text for k in ["기구", "용품", "장비", "덤벨", "요가매트", "매트"]
            ):
                return ["ETC", "소품", "액세서리"]
            if any(
                k in text
                for k in ["신발", "스니커즈", "운동화", "클리트", "축구화", "농구화"]
            ):
                return ["신발", "스포츠/아웃도어화", "스포츠화"]
            if any(k in text for k in ["모자", "캡", "비니"]):
                return ["ETC", "모자", "모자"]
            if any(k in text for k in ["가방", "백팩"]):
                return ["가방", "백팩"]
            if any(
                k in text
                for k in ["아우터", "재킷", "자켓", "점퍼", "바람막이", "윈드브레이커"]
            ):
                return ["의류", _clothing_gender, "아우터", "기타 아우터"]
            if any(
                k in text
                for k in ["하의", "바지", "팬츠", "레깅스", "반바지", "숏팬츠"]
            ):
                return ["의류", _clothing_gender, "하의", "트레이닝/조거 팬츠"]
            return ["의류", _clothing_gender, "상의", "기타 상의"]

        # ── 속옷/홈웨어 ──
        if any(
            k in text
            for k in [
                "속옷",
                "언더웨어",
                "브라",
                "브래지어",
                "팬티",
                "홈웨어",
                "잠옷",
                "파자마",
                "내의",
                "내복",
            ]
        ):
            # 소싱처 카테고리 키워드 기반 분기 (속옷 상의/하의/세트 우선)
            if "속옷 상의" in text or any(k in text for k in ["브라", "브래지어"]):
                return ["속옷/홈웨어", "여성속옷", "여성 속옷 상의"]
            if "속옷 하의" in text or any(k in text for k in ["팬티", "쇼츠"]):
                return ["속옷/홈웨어", "여성속옷", "여성 속옷 하의"]
            if "속옷 세트" in text:
                return ["속옷/홈웨어", "여성속옷", "여성 속옷 세트"]
            if any(k in text for k in ["남성", "남자"]):
                return ["속옷/홈웨어", "남성속옷", "남성 속옷"]
            if any(k in text for k in ["잠옷", "파자마"]) or (
                "홈웨어" in text and "속옷" not in text
            ):
                return ["속옷/홈웨어", "홈웨어", "홈웨어"]
            return ["속옷/홈웨어", "여성속옷", "여성 속옷 세트"]

        # ── 뷰티 ──
        if any(
            k in text
            for k in [
                "뷰티",
                "화장품",
                "코스메틱",
                "스킨케어",
                "메이크업",
                "향수",
                "퍼퓸",
                "헤어케어",
                "바디케어",
                "클렌징",
                "토너",
                "에센스",
                "세럼",
                "로션",
                "크림",
                "선크림",
                "선케어",
                "파운데이션",
                "쿠션",
                "립스틱",
                "립",
                "아이섀도",
                "마스카라",
                "샴푸",
                "린스",
                "트리트먼트",
                "헤어에센스",
                "바디로션",
                "바디워시",
                "핸드크림",
            ]
        ):
            # 스킨케어
            if any(
                k in text
                for k in [
                    "토너",
                    "스킨",
                    "에센스",
                    "세럼",
                    "로션",
                    "크림",
                    "선크림",
                    "선케어",
                    "클렌징",
                    "폼클렌저",
                    "마스크팩",
                    "앰플",
                ]
            ):
                return ["뷰티", "스킨케어", "스킨케어"]
            # 메이크업
            if any(
                k in text
                for k in [
                    "파운데이션",
                    "쿠션",
                    "립스틱",
                    "립",
                    "아이섀도",
                    "마스카라",
                    "블러셔",
                    "컨실러",
                    "프라이머",
                    "메이크업",
                ]
            ):
                return ["뷰티", "메이크업", "메이크업"]
            # 헤어케어
            if any(
                k in text
                for k in [
                    "샴푸",
                    "린스",
                    "컨디셔너",
                    "트리트먼트",
                    "헤어에센스",
                    "헤어오일",
                    "헤어팩",
                    "헤어케어",
                ]
            ):
                return ["뷰티", "헤어케어", "헤어케어"]
            # 바디케어
            if any(
                k in text
                for k in [
                    "바디로션",
                    "바디크림",
                    "바디워시",
                    "바디스크럽",
                    "핸드크림",
                    "바디케어",
                ]
            ):
                return ["뷰티", "바디케어", "바디케어"]
            # 향수
            if any(
                k in text for k in ["향수", "퍼퓸", "오드퍼퓸", "오드뚜왈렛", "디퓨저"]
            ):
                return ["뷰티", "향수", "향수"]
            return ["뷰티", "스킨케어", "스킨케어"]

        # ── 신발 ──
        if any(
            k in text
            for k in [
                "신발",
                "슈즈",
                "스니커즈",
                "운동화",
                "러닝화",
                "조깅화",
                "샌들",
                "슬리퍼",
                "쪼리",
                "플립플랍",
                "뮬",
                "부츠",
                "워커",
                "앵클부츠",
                "첼시부츠",
                "스포츠화",
                "구두",
                "힐",
                "로퍼",
                "플랫",
                "펌프스",
                "축구화",
                "농구화",
                "야구화",
                "여성화",
                "남성화",
                "단화",
            ]
        ):
            _shoe_sub = cat_levels[-1] if len(cat_levels) >= 2 else ""
            # 구두류 → 성별 구분
            if any(
                k in text
                for k in [
                    "구두",
                    "옥스퍼드",
                    "더비",
                    "펌프스",
                    "힐",
                    "하이힐",
                    "킬힐",
                    "단화",
                    "여성화",
                    "남성화",
                ]
            ):
                if _is_female or any(
                    k in text for k in ["여성", "여자", "펌프스", "힐", "여성화"]
                ):
                    return (
                        ["신발", "여성구두", _shoe_sub]
                        if _shoe_sub
                        else ["신발", "여성구두", "여성구두"]
                    )
                return (
                    ["신발", "남성구두", _shoe_sub]
                    if _shoe_sub
                    else ["신발", "남성구두", "남성구두"]
                )
            # 로퍼 → 성별 구분
            if "로퍼" in text:
                if _is_female:
                    return ["신발", "여성구두", "로퍼"]
                if _is_male:
                    return ["신발", "남성구두", "로퍼"]
                return ["신발", "로퍼", "로퍼"]
            # 부츠 → 공용
            if any(
                k in text
                for k in ["부츠", "워커", "앵클부츠", "첼시", "웰링턴", "롱부츠"]
            ):
                return (
                    ["신발", "부츠", _shoe_sub]
                    if _shoe_sub
                    else ["신발", "부츠", "부츠"]
                )
            # 샌들/슬리퍼 → 공용
            if any(
                k in text
                for k in ["샌들", "슬리퍼", "쪼리", "플립플랍", "뮬", "아쿠아슈즈"]
            ):
                return (
                    ["신발", "샌들/슬리퍼", _shoe_sub]
                    if _shoe_sub
                    else ["신발", "샌들/슬리퍼", "샌들/슬리퍼"]
                )
            # 스포츠/아웃도어화 → 러닝화/축구화/농구화 등 종목별 세분류 공용
            if any(
                k in text
                for k in [
                    "러닝화",
                    "러닝",
                    "조깅화",
                    "마라톤",
                    "축구화",
                    "농구화",
                    "야구화",
                    "클리트",
                    "스파이크",
                    "트레킹화",
                    "등산화",
                    "스포츠화",
                ]
            ):
                # 세분류 결정: 소싱처 세분류 우선 → 키워드별 fallback
                if _shoe_sub:
                    _sub = _shoe_sub
                elif any(k in text for k in ["러닝화", "러닝", "조깅화", "마라톤"]):
                    _sub = "러닝화"
                elif "축구화" in text:
                    _sub = "축구화"
                elif "농구화" in text:
                    _sub = "농구화"
                elif "야구화" in text:
                    _sub = "야구화"
                elif any(k in text for k in ["트레킹화", "등산화"]):
                    _sub = "트레킹화"
                else:
                    _sub = "스포츠화"
                return ["신발", "스포츠/아웃도어화", _sub]
            # 기본 → 스니커즈 (공용)
            return (
                ["신발", "스니커즈", _shoe_sub]
                if _shoe_sub
                else ["신발", "스니커즈", "스니커즈"]
            )

        # ── 가방 ──
        if any(
            k in text
            for k in [
                "가방",
                "백팩",
                "파우치",
                "지갑",
                "클러치",
                "토트백",
                "숄더백",
                "크로스백",
                "메신저백",
                "핸드백",
            ]
        ):
            if any(k in text for k in ["지갑", "머니클립", "카드지갑"]):
                return ["가방", "지갑/머니클립"]
            if any(k in text for k in ["백팩", "배낭", "스쿨백"]):
                return ["가방", "백팩"]
            if any(k in text for k in ["토트백", "토트"]):
                return ["가방", "토트백"]
            if any(k in text for k in ["숄더백", "숄더"]):
                return ["가방", "숄더백"]
            if any(k in text for k in ["메신저", "크로스백", "크로스", "슬링백"]):
                return ["가방", "크로스백"]
            if any(k in text for k in ["클러치", "파우치"]):
                return ["가방", "클러치/파우치"]
            return ["가방", "토트백"]

        # ── ETC: 주얼리 ──
        if any(
            k in text
            for k in [
                "주얼리",
                "귀걸이",
                "이어링",
                "목걸이",
                "네클리스",
                "반지",
                "팔찌",
                "브레이슬릿",
                "피어싱",
            ]
        ):
            if any(k in text for k in ["목걸이", "네클리스"]):
                return ["ETC", "주얼리", "목걸이"]
            if any(k in text for k in ["팔찌", "브레이슬릿"]):
                return ["ETC", "주얼리", "팔찌"]
            if any(k in text for k in ["귀걸이", "이어링", "피어싱"]):
                return ["ETC", "주얼리", "귀걸이"]
            if "반지" in text:
                return ["ETC", "주얼리", "반지"]
            return ["ETC", "주얼리", "주얼리"]

        # ── ETC: 시계 ──
        if any(k in text for k in ["시계", "워치"]):
            return ["ETC", "시계", "시계"]

        # ── ETC: 모자 ──
        if any(
            k in text
            for k in [
                "모자",
                "캡",
                "비니",
                "버킷햇",
                "볼캡",
                "베레모",
                "페도라",
                "썬캡",
            ]
        ):
            if any(k in text for k in ["비니"]):
                return ["ETC", "모자", "비니"]
            if any(k in text for k in ["볼캡", "캡", "썬캡"]):
                return ["ETC", "모자", "볼캡"]
            if "버킷햇" in text:
                return ["ETC", "모자", "버킷햇"]
            return ["ETC", "모자", "모자"]

        # ── ETC: 양말 ──
        if any(k in text for k in ["양말", "삭스", "스타킹", "레그워머", "타이즈"]):
            return ["ETC", "양말", "양말"]

        # ── ETC: 머플러/스카프 ──
        if any(k in text for k in ["머플러", "스카프", "숄", "넥워머"]):
            return ["ETC", "머플러/스카프", "머플러/스카프"]

        # ── ETC: 벨트 ──
        if "벨트" in text:
            return ["ETC", "벨트", "벨트"]

        # ── ETC: 기타 액세서리 ──
        if any(
            k in text
            for k in [
                "선글라스",
                "안경",
                "우산",
                "장갑",
                "헤어핀",
                "헤어밴드",
                "액세서리",
                "안경테",
            ]
        ):
            return ["ETC", "액세서리", "액세서리"]

        # ── 원피스/스커트 (항상 여성의류) — 세분류(마지막 레벨) 기준 분기 ──
        if any(k in text for k in ["원피스", "드레스", "스커트", "치마"]):
            _sub = cat_levels[-1] if len(cat_levels) >= 2 else ""
            # 세분류에 스커트/치마 키워드가 있으면 스커트
            if any(k in _sub for k in ["스커트", "치마"]):
                return ["의류", "여성의류", "스커트", _sub]
            # 세분류에 원피스/드레스 키워드가 있으면 원피스
            if any(k in _sub for k in ["원피스", "드레스"]):
                return ["의류", "여성의류", "원피스", _sub]
            # 세분류가 없거나 매칭 안 되면 text 전체에서 판단
            if "드레스" in text:
                return ["의류", "여성의류", "원피스", "미디원피스"]
            return ["의류", "여성의류", "원피스", "미디원피스"]

        # ── 아우터 ──
        if any(
            k in text
            for k in [
                "아우터",
                "재킷",
                "자켓",
                "점퍼",
                "코트",
                "패딩",
                "파카",
                "야상",
                "카디건",
                "집업",
                "베스트",
                "조끼",
                "블루종",
                "바람막이",
            ]
        ):
            if "카디건" in text:
                return ["의류", _clothing_gender, "아우터", "카디건"]
            if any(k in text for k in ["집업", "후드집업", "후드 집업"]):
                return ["의류", _clothing_gender, "아우터", "후드 집업"]
            if any(k in text for k in ["롱패딩", "헤비패딩", "다운점퍼"]):
                return ["의류", _clothing_gender, "아우터", "롱패딩/헤비 아우터"]
            if any(k in text for k in ["숏패딩", "하프패딩"]):
                return ["의류", _clothing_gender, "아우터", "숏패딩/헤비 아우터"]
            if any(
                k in text for k in ["경량패딩", "경량 패딩", "패딩베스트", "다운베스트"]
            ):
                return ["의류", _clothing_gender, "아우터", "경량 패딩/패딩 베스트"]
            if "패딩" in text:
                return ["의류", _clothing_gender, "아우터", "롱패딩/헤비 아우터"]
            if any(
                k in text
                for k in [
                    "트렌치",
                    "환절기코트",
                    "환절기 코트",
                    "봄코트",
                    "가을코트",
                    "스프링코트",
                ]
            ):
                return ["의류", _clothing_gender, "아우터", "환절기 코트"]
            if any(k in text for k in ["더블코트", "더블 코트"]):
                return ["의류", _clothing_gender, "아우터", "겨울 더블 코트"]
            if any(k in text for k in ["싱글코트", "싱글 코트", "겨울코트"]):
                return ["의류", _clothing_gender, "아우터", "겨울 싱글 코트"]
            if "코트" in text:
                return ["의류", _clothing_gender, "아우터", "환절기 코트"]
            if any(k in text for k in ["블레이저", "슈트재킷", "슈트자켓", "정장재킷"]):
                return ["의류", _clothing_gender, "아우터", "슈트/블레이저 재킷"]
            if any(k in text for k in ["레더재킷", "가죽재킷", "라이더스"]):
                return ["의류", _clothing_gender, "아우터", "레더/라이더스 재킷"]
            if any(
                k in text
                for k in ["트러커", "청재킷", "청자켓", "데님재킷", "데님자켓"]
            ):
                return ["의류", _clothing_gender, "아우터", "트러커 재킷"]
            if any(k in text for k in ["블루종", "ma-1", "ma1", "봄버"]):
                return ["의류", _clothing_gender, "아우터", "블루종/MA-1"]
            if any(
                k in text
                for k in [
                    "나일론재킷",
                    "나일론자켓",
                    "코치재킷",
                    "바람막이",
                    "윈드브레이커",
                ]
            ):
                return ["의류", _clothing_gender, "아우터", "나일론/코치 재킷"]
            if any(k in text for k in ["사파리", "헌팅재킷", "헌팅자켓"]):
                return ["의류", _clothing_gender, "아우터", "사파리/헌팅 재킷"]
            if any(k in text for k in ["스타디움", "야구재킷", "야구자켓"]):
                return ["의류", _clothing_gender, "아우터", "스타디움 재킷"]
            if any(
                k in text for k in ["트레이닝재킷", "트레이닝자켓", "져지", "트랙재킷"]
            ):
                return ["의류", _clothing_gender, "아우터", "트레이닝 재킷"]
            if "아노락" in text:
                return ["의류", _clothing_gender, "아우터", "아노락 재킷"]
            if any(k in text for k in ["베스트", "조끼"]):
                return ["의류", _clothing_gender, "아우터", "베스트"]
            return ["의류", _clothing_gender, "아우터", "기타 아우터"]

        # ── 하의 ──
        if any(
            k in text
            for k in [
                "바지",
                "팬츠",
                "하의",
                "데님",
                "청바지",
                "슬랙스",
                "반바지",
                "조거",
                "트레이닝",
                "점프수트",
                "오버올",
                "레깅스",
            ]
        ):
            if any(k in text for k in ["점프수트", "점프슈트", "오버올", "올인원"]):
                return ["의류", _clothing_gender, "하의", "점프 슈트/오버올"]
            if any(k in text for k in ["청바지", "데님", "진"]):
                return ["의류", _clothing_gender, "하의", "데님 팬츠"]
            if any(k in text for k in ["슬랙스", "슈트팬츠", "정장바지", "드레스팬츠"]):
                return ["의류", _clothing_gender, "하의", "슈트 팬츠/슬랙스"]
            if any(k in text for k in ["반바지", "숏팬츠", "버뮤다"]):
                return ["의류", _clothing_gender, "하의", "숏 팬츠"]
            if any(k in text for k in ["트레이닝", "조거", "스웨트팬츠", "저지팬츠"]):
                return ["의류", _clothing_gender, "하의", "트레이닝/조거 팬츠"]
            return ["의류", _clothing_gender, "하의", "코튼 팬츠"]

        # ── 상의 ──
        if any(
            k in text
            for k in [
                "상의",
                "티셔츠",
                "셔츠",
                "블라우스",
                "니트",
                "스웨터",
                "후드",
                "맨투맨",
                "탑",
                "반팔",
                "긴팔",
                "민소매",
                "나시",
            ]
        ):
            if any(k in text for k in ["블라우스", "남방", "와이셔츠", "드레스셔츠"]):
                return ["의류", _clothing_gender, "상의", "셔츠/블라우스"]
            if "셔츠" in text and "티셔츠" not in text:
                return ["의류", _clothing_gender, "상의", "셔츠/블라우스"]
            if any(k in text for k in ["니트", "스웨터", "울", "케이블니트"]):
                return ["의류", _clothing_gender, "상의", "니트/스웨터"]
            if any(k in text for k in ["맨투맨", "스웨트셔츠", "크루넥", "스웨트"]):
                return ["의류", _clothing_gender, "상의", "맨투맨/스웨트"]
            if any(k in text for k in ["피케", "카라티", "폴로"]):
                return ["의류", _clothing_gender, "상의", "피케/카라 티셔츠"]
            if any(
                k in text for k in ["민소매", "나시", "탱크탑", "슬리브리스", "홀터"]
            ):
                return ["의류", _clothing_gender, "상의", "민소매 티셔츠"]
            if (
                any(k in text for k in ["후드티", "후디", "후드티셔츠", "후드 티셔츠"])
                or "후드" in text
            ):
                return ["의류", _clothing_gender, "상의", "후드 티셔츠"]
            if any(k in text for k in ["반팔", "반소매", "숏슬리브"]):
                return ["의류", _clothing_gender, "상의", "반소매 티셔츠"]
            if any(k in text for k in ["긴팔", "긴소매", "롱슬리브"]):
                return ["의류", _clothing_gender, "상의", "긴소매 티셔츠"]
            return ["의류", _clothing_gender, "상의", "기타 상의"]

        # ── 2차 광역 매핑: 패션/의류 관련 ──
        if any(
            k in text
            for k in [
                "의류",
                "패션",
                "fashion",
                "wear",
                "clothing",
                "여성패션",
                "남성패션",
                "여성의류",
                "남성의류",
                "캐주얼",
                "스트릿",
                "포멀",
                "오피스룩",
                "데이트룩",
            ]
        ):
            return ["의류", _clothing_gender, "상의", "기타 상의"]

        # ── 최종 fallback: 원본 카테고리 최대 4단계 그대로 ──
        return cat_levels[:4]

    @staticmethod
    async def _save_tokens_if_changed(session, account, client) -> None:
        """토큰이 갱신됐으면 계정에 저장.

        중요: 이 함수는 절대 예외를 바깥으로 던지면 안 된다.
        토큰 저장 실패가 이미 성공한 상품 등록을 실패로 뒤집으면
        재시도 로직이 돌아가서 카페24에 중복 상품이 생성되는 버그가 발생한다.
        (SQLAlchemy detached instance 에러 등으로 중복 등록 사고 발생 이력 있음)
        """
        if not account:
            return
        try:
            extras = account.additional_fields or {}
            old_token = extras.get("accessToken", "")
            if client.access_token and client.access_token != old_token:
                # 새 dict 객체로 교체해야 SQLAlchemy JSON 변경 감지됨
                account.additional_fields = {
                    **extras,
                    "accessToken": client.access_token,
                    **(
                        {"refreshToken": client.refresh_token}
                        if client.refresh_token
                        else {}
                    ),
                }
                session.add(account)
                await session.commit()
                logger.info("[카페24] 갱신된 토큰 계정에 저장 완료")
        except Exception as e:
            logger.warning(f"[카페24] 토큰 저장 실패 (무시): {e}")
            try:
                await session.rollback()
            except Exception:
                pass
