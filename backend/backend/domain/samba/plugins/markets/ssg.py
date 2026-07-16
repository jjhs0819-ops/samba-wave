"""SSG(신세계몰) 마켓 플러그인.

기존 dispatcher._handle_ssg 로직을 플러그인 구조로 추출.
SSGClient를 통해 인프라 조회 + 상품 변환 + 등록/수정 처리.
"""

from __future__ import annotations

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.utils.logger import logger


class SSGPlugin(MarketPlugin):
    market_type = "ssg"
    policy_key = "신세계몰(전시)"
    required_fields = ["name", "sale_price"]

    def _validate_category(self, category_id: str) -> str:
        # SSG 전시카테고리 ID(dispCtgId)는 숫자이지만, base의 isdigit 검사가
        # 비정상 매핑값을 잘못 차단할 수 있으므로 롯데ON과 동일하게 pass-through.
        return category_id or ""

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        """SSGClient.transform_product 위임."""
        from backend.domain.samba.proxy.ssg import SSGClient

        api_key = kwargs.get("api_key", "")
        store_id = kwargs.get("store_id", "6004")
        infra = kwargs.get("infra", {})
        client = SSGClient(api_key, site_no=store_id)
        return client.transform_product(product, category_id, infra=infra)

    async def execute(
        self,
        session,
        product: dict,
        creds: dict,
        category_id: str,
        account,
        existing_no: str,
    ) -> dict[str, Any]:
        """SSG 상품 등록/수정 — 전체 로직."""
        from backend.domain.samba.proxy.ssg import SSGClient

        api_key = creds.get("apiKey", "")
        if not api_key:
            return {"success": False, "message": "SSG 인증키가 비어있습니다."}

        # transmitting stuck으로 인해 itemId가 "__exists__"로 저장된 상품:
        # SSG에는 이미 등록됐지만 실제 itemId를 모름 → 재등록/수정 차단 + 경고
        if existing_no == "__exists__":
            return {
                "success": False,
                "message": "SSG itemId 미확인 (신세계몰 셀러센터에서 상품번호 확인 후 수동 입력 필요)",
                "_skip_retry": True,
            }

        # 옵션별 가격 불균일 상품은 SSG 전송 제외.
        # SSG 온라인 상품은 옵션별 다른 매가를 지원하지 않는다("온라인 상품의 매가는
        # 1개만 입력 가능 (00007)"). 옵션가가 1원이라도 다르면 등록/수정하지 않는다.
        _opt_prices = {
            int(o.get("price") or 0)
            for o in (product.get("options") or [])
            if isinstance(o, dict) and int(o.get("price") or 0) > 0
        }
        if len(_opt_prices) > 1:
            return {
                "success": False,
                "message": (
                    f"옵션별 가격 상이({len(_opt_prices)}종) — SSG는 옵션별 다른 "
                    "매가 미지원, 전송 제외"
                ),
                "_skip_retry": True,
            }

        # 전시카테고리 미매핑 시 등록 불가 — 명확한 에러 반환
        if not category_id:
            product_name = product.get("name", "")
            return {
                "success": False,
                "message": f"신세계몰 전시카테고리가 매핑되지 않았습니다. 카테고리 매핑 후 다시 시도하세요. (상품: {product_name[:30]})",
            }

        store_id = creds.get("storeId", "6004")
        client = SSGClient(api_key, site_no=store_id)

        # 배송비/주소 인프라 데이터 조회
        # 경량 모드: 설정에 인프라 ID가 모두 있으면 fetch_infra() API 호출 스킵
        skip_image = product.get("_skip_image_upload", False) and bool(existing_no)
        if skip_image:
            _infra_keys = (
                "whoutAddrId",
                "snbkAddrId",
                "whoutShppcstId",
                "retShppcstId",
            )
            _all_present = all(creds.get(k) for k in _infra_keys)
            if _all_present:
                # 배송 ID는 설정값 사용, 원산지 코드는 fetch_infra 캐시에서 취득
                _full_infra = await client.fetch_infra()
                infra: dict[str, Any] = {
                    "origin_code_map": _full_infra.get("origin_code_map", {})
                }
                logger.info(
                    "[SSG] 경량 가격/재고 모드 → 배송 ID 설정값 사용, 원산지 코드만 별도 조회"
                )
            else:
                infra = await client.fetch_infra()
                logger.info(
                    f"[SSG] 경량 모드이나 인프라 ID 부족 → fetch_infra 호출: {list(infra.keys())}"
                )
        else:
            infra = await client.fetch_infra()
            logger.info(f"[SSG] 인프라 조회 완료: {list(infra.keys())}")

        # 설정 페이지 값을 infra에 주입 (설정값이 있으면 fetch_infra 조회값 우선 덮어쓰기)
        setting_shppcst_ids = {
            "whoutShppcstId": creds.get("whoutShppcstId", ""),
            "retShppcstId": creds.get("retShppcstId", ""),
            "addShppcstIdJeju": creds.get("addShppcstIdJeju", ""),
            "addShppcstIdIsland": creds.get("addShppcstIdIsland", ""),
            "whoutAddrId": creds.get("whoutAddrId", ""),
            "snbkAddrId": creds.get("snbkAddrId", ""),
        }
        for k, v in setting_shppcst_ids.items():
            if v:
                infra[k] = v

        # 필수 배송 인프라 ID 검증 — 없으면 SSG API 필수값 오류 발생
        missing_infra = []
        if not infra.get("whoutAddrId"):
            missing_infra.append("출고주소ID(whoutAddrId)")
        if not infra.get("snbkAddrId"):
            missing_infra.append("반품주소ID(snbkAddrId)")
        if not infra.get("whoutShppcstId"):
            missing_infra.append("출고배송비ID(whoutShppcstId)")
        if not infra.get("retShppcstId"):
            missing_infra.append("반품배송비ID(retShppcstId)")
        if missing_infra:
            return {
                "success": False,
                "message": f"SSG 배송 설정 누락: {', '.join(missing_infra)}. 설정 페이지에서 배송정보를 확인하세요.",
            }

        # 정책 브랜드 매핑 추출
        brand_mappings: list[dict] = creds.get("ssgBrandMappings") or []

        # 동적 브랜드 해석 (이슈 #358) — ssgBrandMappings/하드코딩 CONTRACTED_BRANDS로
        # 미해결인 브랜드를 계정 계약목록(listBrand) exact-match로 보강 주입.
        # listBrand 는 계정별 계약 브랜드만 반환하므로, 그 계정이 계약한 브랜드만 복구되고
        # 미계약 브랜드(예: 써코니·조던)는 그대로 기타(9999999999) 폴백 유지된다.
        _brand_raw = (product.get("brand") or "").strip()
        _mfr_raw = (product.get("manufacturer") or "").strip()
        _cand = _brand_raw or _mfr_raw
        if _cand:
            _norm = SSGClient._norm_brand(_cand)
            _already = {
                SSGClient._norm_brand(m.get("brandNm", ""))
                for m in brand_mappings
                if isinstance(m, dict) and m.get("brandNm")
            }
            _hardcoded_ok = SSGClient.match_brand(_brand_raw)[0] != "9999999999" or (
                _mfr_raw and SSGClient.match_brand(_mfr_raw)[0] != "9999999999"
            )
            if _norm not in _already and not _hardcoded_ok:
                try:
                    _cmap = await client.get_contracted_brand_map()
                    _bid = _cmap.get(SSGClient._norm_brand(_brand_raw)) or (
                        _cmap.get(SSGClient._norm_brand(_mfr_raw)) if _mfr_raw else None
                    )
                    if _bid:
                        brand_mappings = list(brand_mappings) + [
                            {"brandNm": _cand, "brandId": _bid}
                        ]
                        logger.info(
                            f"[SSG] 브랜드 동적해석: {_cand!r} → brandId={_bid}"
                        )
                    elif _cand:
                        logger.warning(
                            f"[SSG] 브랜드 미해결(계약목록에 없음, 기타 폴백): {_cand!r}"
                        )
                except Exception as _be:  # noqa: BLE001
                    logger.warning(f"[SSG] 브랜드 동적해석 실패(무시): {_be}")

        # 설정에서 마진율/배송소요일/구매수량 제한 추출 (정책값 우선, 설정값 폴백)
        margin_rate = int(creds.get("marginRate") or 0)
        shpp_rqrm_dcnt = int(creds.get("shppRqrmDcnt") or 3)
        day_max_qty = int(product.get("_day_max_qty") or creds.get("dayMaxQty") or 5)
        once_min_qty = int(product.get("_once_min_qty") or creds.get("onceMinQty") or 1)
        once_max_qty = int(product.get("_once_max_qty") or creds.get("onceMaxQty") or 5)

        # 추가수수료율 역산 + 100원 단위 올림
        import math as _math

        extra_fee_rate = float(creds.get("extraFeeRate") or 0)
        _orig_price = int(product.get("sale_price", 0) or 0)
        if _orig_price > 0:
            _new_price = _orig_price
            if extra_fee_rate > 0:
                _new_price = _math.ceil(_new_price / (1 - extra_fee_rate / 100))
            _new_price = _math.ceil(_new_price / 100) * 100
            if _new_price != _orig_price:
                product = dict(product)
                product["sale_price"] = _new_price

        # 고시정보 정책값 주입
        notice_overrides: dict[str, str] = {}
        _notice_field_map = {
            "ssgNoticeGroup": "_ssg_notice_group",
            "ssgNoticeMaterial": "_ssg_notice_material",
            "ssgNoticeColor": "_ssg_notice_color",
            "ssgNoticeSize": "_ssg_notice_size",
            "ssgNoticeImport": "_ssg_import_yn",
            "ssgNoticeImporter": "_ssg_notice_importer",
            "ssgNoticeCaution": "_ssg_notice_caution",
            "ssgNoticeAsContact": "_ssg_notice_as_contact",
            "ssgNoticeManufacturer": "_ssg_notice_manufacturer",
            "ssgNoticeOrigin": "_ssg_notice_origin",
            "ssgNoticeDropProps": "_ssg_notice_drop_props",
        }
        for cred_key, prod_key in _notice_field_map.items():
            val = creds.get(cred_key)
            if val:
                notice_overrides[prod_key] = val
        if notice_overrides:
            product = {**product, **notice_overrides}

        # A/S 정보 주입 — 고시정보 통합 연락처 우선, 없으면 설정값
        if not creds.get("ssgNoticeAsContact"):
            as_phone = creds.get("asPhone") or ""
            as_message = creds.get("asMessage") or ""
            if as_phone:
                product = {**product, "_as_phone": as_phone}
            if as_message:
                product = {**product, "_as_message": as_message}

        # category_id = 전시카테고리 ID, _std_category_id = 표준카테고리 ID
        std_category_id = product.get("_std_category_id", "") or ""
        if not std_category_id:
            logger.warning(
                "[SSG] _std_category_id 없음 — stdCtgId 빈값으로 전송. 등록 실패 가능."
            )
        logger.info(
            f"[SSG] 전시카테고리={category_id!r}, 표준카테고리={std_category_id!r}"
        )

        # SSG.COM(6005) 메인매장 전시카테고리 자동 조회
        # ssgComEnabled=true 설정 시에만 실행 — 신세계몰(6004) 단일 셀러는 불필요(API 2회 낭비)
        # 1단계: 신세계몰(6004) 카테고리 ID → 카테고리명 조회
        # 2단계: 해당 leaf명으로 SSG.COM(6005) 전시카테고리 검색
        main_category_id = ""
        # 6005 후보 dispCtgId 유사도 순 리스트 — 등록 거부 시 다음 후보로 순차 재시도용
        main_cat_candidates: list[str] = []
        _ssg_com_enabled = creds.get("ssgComEnabled") in (True, "true", "True", "1")

        async def _lookup_6005_main_cat() -> None:
            """신세계몰(6004) 카테고리명으로 SSG.COM(6005) 메인매장 전시카테고리를 유사도 검색.

            ssgComEnabled off 매장이 6005 필수로 등록 거부될 때 재호출(self-heal)도 한다.
            결과를 main_category_id / main_cat_candidates 에 채운다.
            """
            nonlocal main_category_id, main_cat_candidates
            try:
                # 1단계: 신세계몰 카테고리 이름 조회
                name_resp = await client._call_api(
                    "GET",
                    "/common/0.1/displayCategory.ssg",
                    params={"dispCtgId": category_id},
                )

                def _extract_cats(resp: dict) -> list:
                    raw = resp.get("result", {}).get("displayCategorys", [])
                    if isinstance(raw, dict):
                        inner = raw.get("category", [])
                        return [inner] if isinstance(inner, dict) else (inner or [])
                    if isinstance(raw, list):
                        result = []
                        for item in raw:
                            if not isinstance(item, dict):
                                continue
                            cat = item.get("category")
                            if isinstance(cat, dict):
                                result.append(cat)
                            elif isinstance(cat, list):
                                result.extend(cat)
                            else:
                                result.append(item)
                        return result
                    return []

                name_cats = _extract_cats(name_resp)
                leaf_name = ""
                path_6004 = ""  # 6005 후보 유사도 비교 기준 (신세계몰 전체 경로)
                if name_cats:
                    # category_id와 일치하는 항목 우선, 없으면 마지막 항목(가장 세분류)
                    target = next(
                        (
                            c
                            for c in name_cats
                            if str(c.get("dispCtgId", "")) == category_id
                        ),
                        name_cats[-1],
                    )
                    path = target.get("dispCtgPathNm", "") or target.get(
                        "dispCtgNm", ""
                    )
                    path_6004 = path
                    leaf_name = (
                        path.split(">")[-1].strip() if ">" in path else path.strip()
                    )
                    logger.info(f"[SSG] 신세계몰 카테고리 이름: {leaf_name!r}")

                # 2단계: SSG.COM(6005)에서 leaf_name 검색
                # 검색 결과 [0] 무검증 선택 금지 — leaf명만으로는 영유아/아동 등
                # 엉뚱한 매장 카테고리가 [0]에 와서 "매장 전시 불가" 거부 발생.
                # 6004 전체 경로와 토큰 유사도로 정렬해 가장 적합한 후보를 선택한다.
                if leaf_name:
                    keywords = [leaf_name]
                    short = leaf_name.split("/")[0].strip()
                    if short and short != leaf_name:
                        keywords.append(short)

                    # 영유아/아동 등 — 6004 경로에 없는데 후보 경로에만 있으면 페널티
                    _penalty_tokens = (
                        "영유아",
                        "유아",
                        "아동",
                        "임부",
                        "베이비",
                        "키즈",
                        "신생아",
                    )

                    def _path_tokens(_p: str) -> set[str]:
                        _out: set[str] = set()
                        for _seg in _p.replace(">", " ").replace("/", " ").split():
                            if _seg.strip():
                                _out.add(_seg.strip())
                        return _out

                    _ref_tokens = _path_tokens(path_6004)

                    def _cand_score(_cand: dict) -> int:
                        _cp = _cand.get("dispCtgPathNm", "") or _cand.get(
                            "dispCtgNm", ""
                        )
                        _overlap = len(_ref_tokens & _path_tokens(_cp))
                        _penalty = sum(
                            3
                            for _t in _penalty_tokens
                            if _t in _cp and _t not in path_6004
                        )
                        return _overlap - _penalty

                    _all_cands: list[dict] = []
                    _seen_ids: set[str] = set()
                    for kw in keywords:
                        com_resp = await client.search_display_categories(
                            kw, site_no="6005"
                        )
                        for _c in _extract_cats(com_resp):
                            _cid = str(_c.get("dispCtgId", ""))
                            if _cid and _cid not in _seen_ids:
                                _seen_ids.add(_cid)
                                _all_cands.append(_c)

                    if _all_cands:
                        _all_cands.sort(key=_cand_score, reverse=True)
                        main_cat_candidates = [
                            str(_c.get("dispCtgId", ""))
                            for _c in _all_cands
                            if _c.get("dispCtgId")
                        ]
                        main_category_id = main_cat_candidates[0]
                        _best_path = _all_cands[0].get("dispCtgPathNm", "")
                        logger.info(
                            f"[SSG] SSG.COM(6005) 전시카테고리 유사도 선택: {main_category_id} "
                            f"({_best_path!r}, 후보 {len(main_cat_candidates)}개)"
                        )
                    if not main_category_id:
                        # 6005 검색 결과 없음/부적합 → 신발·샌들 계열 leaf명/경로 키워드로
                        # 6005 전시카테고리 직접 매핑(fallback). 매핑 코드는 6005 실측 확인값.
                        # "메인매장 카테고리 필수" 거부로 self-heal도 못 채우던 신발 카테고리
                        # (런닝화/샌들/스포츠신발/등산화 등)를 처음부터 채운다.
                        _fb_src = f"{leaf_name} {path_6004}"
                        _FB_6005 = [
                            ("런닝화", "6000200591"),
                            ("워킹화", "6000200591"),
                            ("등산화", "6000204830"),
                            ("트레킹", "6000204830"),
                            ("트래킹", "6000204830"),
                            ("스포츠신발", "6000204826"),
                            ("샌들", "6000204965"),
                            ("슬리퍼", "6000204965"),
                            ("운동화", "6000200209"),
                            ("스니커즈", "6000200209"),
                            ("스포츠화", "6000204970"),
                            ("신발", "6000204970"),
                        ]
                        for _kw, _cid in _FB_6005:
                            if _kw in _fb_src:
                                main_category_id = _cid
                                main_cat_candidates = [_cid]
                                logger.info(
                                    f"[SSG] 6005 fallback 매핑: '{_kw}'→{_cid} "
                                    f"(원경로={_fb_src.strip()!r})"
                                )
                                break
                    if not main_category_id:
                        logger.warning(
                            f"[SSG] SSG.COM(6005) '{leaf_name}' 검색 결과 없음"
                        )
            except Exception as _e:
                logger.warning(f"[SSG] SSG.COM(6005) 전시카테고리 조회 실패: {_e}")

        # 경량 수정(skip_image=price/stock-only + existing_no)에는 전시카테고리
        # 후보 재산출 불필요 — displayCategory/listDispCtg 다중 호출이 SSG 응답 지연 시
        # 호출당 30초 타임아웃 누적 → 상품당 300초 초과로 SSG 전송 전멸
        # (issue #354). 기존 6005 보존은 하단 get_item_detail 경로가 담당.
        if category_id and _ssg_com_enabled and not skip_image:
            await _lookup_6005_main_cat()

        # 6005 전시카테고리 보존(회귀 #312 보정) — 수정(existing_no) 인데 위 조회로
        # main_category_id 를 못 채운 경우, 기존 등록 아이템이 이미 6005 카테고리를
        # 보유하면 그대로 보존한다. b21b361d 가 6005 조회를 ssgComEnabled opt-in(기본 off)
        # 으로 바꾼 뒤, 그 이전 6005 등록분을 수정하면 dispCtgs 에서 6005 가 빠져
        # SSG 가 "SSG.COM몰 메인매장 카테고리 1개 이상 필수" 로 거부하던 문제 차단.
        # 6004 전용 아이템은 6005 mainDisplayCategory 가 없어 main_category_id 빈값 유지 →
        # 의도치 않은 6005 재등록 없음. 신규등록(existing_no 없음)은 상세조회 대상 아님.
        if existing_no and not main_category_id:
            try:
                _detail = await client.get_item_detail(existing_no)
                _kept = client.extract_main_disp_ctg(_detail, "6005")
                if _kept:
                    main_category_id = _kept
                    main_cat_candidates = [_kept]
                    logger.info(
                        f"[SSG] 기존 6005 전시카테고리 보존: "
                        f"itemId={existing_no} dispCtgId={_kept}"
                    )
            except Exception as _e:
                logger.warning(f"[SSG] 기존 6005 카테고리 보존 조회 실패(무시): {_e}")

            # 기존 6005도 없는 수정건 → 6005 조회+fallback 매핑 1회 수행.
            # 경량 수정(skip_image)은 위에서 _lookup_6005_main_cat 을 건너뛰므로,
            # 기존 등록에 6005가 없으면 "메인매장 카테고리 필수" 로 계속 거부됐다
            # (self-heal 은 신규등록 전용이라 수정건은 못 잡음). 여기서 1회 채운다.
            if not main_category_id and category_id and _ssg_com_enabled:
                await _lookup_6005_main_cat()

        # 무신사 등 referer 차단 CDN URL을 R2로 미러링
        # — SSG는 등록 URL을 자체 서버가 fetch하므로 핫링크 차단 시 워터마크 이미지로 캐싱됨
        try:
            from backend.domain.samba.image.service import ImageTransformService

            _img_svc = ImageTransformService(session)
            _images = product.get("images") or []
            _detail_images = product.get("detail_images") or []
            _detail_html = product.get("detail_html") or ""
            if _images or _detail_images or _detail_html:
                product = dict(product)
                _pid = product.get("id")
                if _images:
                    product["images"], _ = await _img_svc.mirror_with_persistence(
                        _pid, _images
                    )
                if _detail_images:
                    (
                        product["detail_images"],
                        _,
                    ) = await _img_svc.mirror_with_persistence(_pid, _detail_images)
                if _detail_html:
                    _mirrored_html = await _img_svc.mirror_urls_in_html(_detail_html)
                    # 미러 실패로 남은 외부 <img>(puma_notice 깨진 이미지·용량초과 등)
                    # 제거 — SSG가 fetch 못 해 "파일 다운로드 도중 오류"로 상품 전체
                    # 등록 거부되는 것 방지. 미러된 정상 이미지는 보존.
                    product["detail_html"] = await _img_svc.strip_external_imgs_in_html(
                        _mirrored_html
                    )
                if not product.get("images"):
                    return {
                        "success": False,
                        "message": "SSG 등록 실패: 이미지 미러링 후 사용 가능한 이미지가 없습니다.",
                    }
        except Exception as e:
            logger.warning(f"[SSG] 이미지 미러링 단계 오류 — 원본 URL 유지: {e}")

        try:
            data = client.transform_product(
                product,
                category_id,
                std_category_id=std_category_id,
                main_category_id=main_category_id,
                infra=infra,
                margin_rate=margin_rate,
                shpp_rqrm_dcnt=shpp_rqrm_dcnt,
                day_max_qty=day_max_qty,
                once_min_qty=once_min_qty,
                once_max_qty=once_max_qty,
                brand_mappings=brand_mappings,
            )
        except Exception as e:
            import traceback as _tb

            logger.error(f"[SSG] transform_product 예외: {e}\n{_tb.format_exc()}")
            return {
                "success": False,
                "message": f"SSG 상품 데이터 변환 실패: {str(e)[:200]}",
            }

        # 선제 멱등 가드(#321) — 신규등록 직전 splVenItemId(=수집상품 id)로 기존 live 등록 검색.
        # SSG insertItem 은 비멱등(호출마다 새 itemId)이라, itemNm 포맷이 코드 변경으로
        # 바뀌면 동일 상품이 2개 itemId 로 중복등록됨. 안정키로 미리 찾아 update 전환.
        if not existing_no:
            _spl_id = str(product.get("id") or "")
            if _spl_id:
                try:
                    _found = await client.find_live_item_id_by_spl_ven(_spl_id)
                    if _found:
                        logger.info(
                            f"[SSG] 멱등가드 — splVenItemId={_spl_id} 기존 등록 발견 → "
                            f"update 전환: itemId={_found}"
                        )
                        existing_no = _found
                except Exception as e:
                    logger.warning(f"[SSG] splVenItemId 선제검색 실패(무시): {e}")

        # 기존 상품번호가 있으면 수정, 없으면 신규등록
        if existing_no:
            data["itemId"] = existing_no
            result = await client.update_product(data)
            # 영구판매중지 상품은 수정 불가 → 상품번호 초기화 후 신규등록
            result_data_chk = result.get("data", {})
            if isinstance(result_data_chk, dict):
                res_chk = result_data_chk.get("result", {})
                if isinstance(res_chk, dict):
                    msg_chk = (
                        res_chk.get("resultDesc", "")
                        or res_chk.get("resultMessage", "")
                        or ""
                    )
                    if "영구판매중지" in msg_chk:
                        logger.info(
                            f"[SSG] 영구판매중지 상품 감지 → 상품번호 초기화 후 신규등록: itemId={existing_no}"
                        )
                        data.pop("itemId", None)
                        result = await client.register_product(data)
                        result["_clear_product_no"] = (
                            True  # 호출자에서 DB 상품번호 초기화
                        )
        else:
            result = await client.register_product(data)

        # 고시항목(itemMngPropId) 자동 self-heal 재시도 (insertItem 한정, 최대 8회 loop)
        # SSG 고시분류(ClsId)마다 요구 항목이 달라(#274 근본원인), 신발/가방/잡화/수영/골프
        # 등에서 ①'고시분류에 없는 값' 거부 ②'필수 항목 누락' 이 순차 발생.
        # ① → 해당 itemMngPropId drop 누적,  ② → 항목이름으로 값 유추해 add 누적.
        # 진전이 없거나 성공할 때까지 재변환·재전송 반복.
        if not data.get("itemId"):
            import re as _re_ssg

            def _resolve_notice_content(_nm: str) -> str:
                _n = _nm or ""
                _fb = "상세페이지 참조"
                _up = _n.upper()
                if "전화" in _n or "연락처" in _n or "A/S" in _n or "AS " in _up:
                    return (
                        creds.get("asPhone")
                        or product.get("_ssg_notice_as_contact")
                        or _fb
                    )
                if "소재" in _n or "재질" in _n or "섬유" in _n:
                    return product.get("material") or _fb
                if "색상" in _n or "색깔" in _n:
                    return product.get("color") or _fb
                if (
                    "치수" in _n
                    or "크기" in _n
                    or "사이즈" in _n
                    or "규격" in _n
                    or "제품별" in _n
                ):
                    return (
                        product.get("size_notice") or product.get("sizeNotice") or _fb
                    )
                if "제조국" in _n or "원산지" in _n:
                    return product.get("origin") or _fb
                if (
                    "제조자" in _n
                    or "제조사" in _n
                    or "수입자" in _n
                    or "판매자" in _n
                    or "생산자" in _n
                ):
                    return product.get("manufacturer") or product.get("brand") or _fb
                if "품질보증" in _n or "보증기준" in _n:
                    return "관련 법 및 소비자분쟁해결 규정에 따름"
                return _fb

            for _mng_attempt in range(20):
                _retry_data = result.get("data", {}) if isinstance(result, dict) else {}
                _retry_res = (
                    _retry_data.get("result", {}) if isinstance(_retry_data, dict) else {}
                )
                if not isinstance(_retry_res, dict):
                    break
                _retry_code = str(_retry_res.get("resultCode", "") or "")
                if not _retry_code or _retry_code in ("00", "SUCCESS"):
                    break
                _retry_msg = (
                    _retry_res.get("resultDesc", "")
                    or _retry_res.get("resultMessage", "")
                    or ""
                )
                if "itemMngPropId" not in _retry_msg:
                    break

                _changed = False

                if "누락" in _retry_msg:
                    # 필수 항목 누락 → 값 채워 add. 형식: [itemMngPropId : 항목명 (0000000075)]
                    _miss = _re_ssg.findall(
                        r"itemMngPropId\s*:\s*([^()\[\]]+?)\s*\((\d+)\)", _retry_msg
                    )
                    _add_list = list(product.get("_ssg_notice_add_attrs") or [])
                    _add_ids = {
                        str(a.get("itemMngPropId"))
                        for a in _add_list
                        if isinstance(a, dict)
                    }
                    for _nm, _num in _miss:
                        _num = _num.strip()
                        if _num and _num not in _add_ids:
                            _add_list.append(
                                {
                                    "itemMngPropId": _num,
                                    "itemMngCntt": _resolve_notice_content(_nm),
                                }
                            )
                            _add_ids.add(_num)
                            _changed = True
                    if _changed:
                        product = {**product, "_ssg_notice_add_attrs": _add_list}
                else:
                    # 고시분류에 없는 값 → drop 누적
                    _rejected_ids = _re_ssg.findall(
                        r"itemMngPropId\s*:\s*(\d+)", _retry_msg
                    )
                    _existing_drop = product.get("_ssg_notice_drop_props") or []
                    if isinstance(_existing_drop, str):
                        _existing_drop = [
                            s.strip()
                            for s in _existing_drop.replace(" ", ",").split(",")
                            if s.strip()
                        ]
                    _prev_set = {str(x) for x in _existing_drop}
                    _merged_drop = sorted(_prev_set | set(_rejected_ids))
                    # drop 하려는 항목이 방금 add한 것이면 add에서도 제거(무한 add↔drop 방지)
                    _add_list = [
                        a
                        for a in (product.get("_ssg_notice_add_attrs") or [])
                        if str(a.get("itemMngPropId")) not in set(_rejected_ids)
                    ]
                    if set(_merged_drop) != _prev_set:
                        product = {
                            **product,
                            "_ssg_notice_drop_props": _merged_drop,
                            "_ssg_notice_add_attrs": _add_list,
                        }
                        _changed = True

                if not _changed:
                    logger.warning(
                        f"[SSG] 고시 self-heal 중단 — 진전 없음: {_retry_msg[:120]}"
                    )
                    break
                logger.warning(
                    f"[SSG] 고시 self-heal 재시도({_mng_attempt + 1}/20): "
                    f"drop={product.get('_ssg_notice_drop_props')} "
                    f"add={[a.get('itemMngPropId') for a in (product.get('_ssg_notice_add_attrs') or [])]}"
                )
                try:
                    data = client.transform_product(
                        product,
                        category_id,
                        std_category_id=std_category_id,
                        main_category_id=main_category_id,
                        infra=infra,
                        margin_rate=margin_rate,
                        shpp_rqrm_dcnt=shpp_rqrm_dcnt,
                        day_max_qty=day_max_qty,
                        once_min_qty=once_min_qty,
                        once_max_qty=once_max_qty,
                        brand_mappings=brand_mappings,
                    )
                    result = await client.register_product(data)
                except Exception as e:
                    import traceback as _tb

                    logger.error(
                        f"[SSG] 고시 self-heal 재시도 실패: {e}\n{_tb.format_exc()}"
                    )
                    break

        # ssgComEnabled off 매장 self-heal — "SSG.COM몰 메인매장 카테고리는 1개 이상 필수"
        # 거부 시 그 자리에서 6005 조회를 1회 수행 후 재시도. 스위치를 안 켜도 자동 복구되어
        # 매장별 수동 설정을 기억할 필요가 없다.
        if not data.get("itemId") and not main_category_id and category_id:
            _hd = result.get("data", {}) if isinstance(result, dict) else {}
            _hr = _hd.get("result", {}) if isinstance(_hd, dict) else {}
            if isinstance(_hr, dict):
                _hc = str(_hr.get("resultCode", "") or "")
                _hmsg = _hr.get("resultDesc", "") or _hr.get("resultMessage", "") or ""
                if (
                    _hc
                    and _hc not in ("00", "SUCCESS")
                    and "메인매장 카테고리" in _hmsg
                ):
                    logger.warning(
                        "[SSG] 메인매장 카테고리 필수 거부 → ssgComEnabled 무관 6005 자동 조회 후 재시도"
                    )
                    await _lookup_6005_main_cat()
                    if main_category_id:
                        try:
                            data = client.transform_product(
                                product,
                                category_id,
                                std_category_id=std_category_id,
                                main_category_id=main_category_id,
                                infra=infra,
                                margin_rate=margin_rate,
                                shpp_rqrm_dcnt=shpp_rqrm_dcnt,
                                day_max_qty=day_max_qty,
                                once_min_qty=once_min_qty,
                                once_max_qty=once_max_qty,
                                brand_mappings=brand_mappings,
                            )
                            result = await client.register_product(data)
                        except Exception as e:
                            import traceback as _tb

                            logger.error(
                                f"[SSG] 메인매장 카테고리 self-heal 재시도 실패: {e}\n{_tb.format_exc()}"
                            )

        # 6005 메인매장 전시카테고리 거부 자동 재시도 (신규등록 한정)
        # "잘못된 카테고리 정보입니다 … 전시 할 수 없습니다" 거부 시
        # 유사도 차순위 후보로 dispCtgId 만 교체해 순차 재시도(최대 3개).
        if not data.get("itemId") and len(main_cat_candidates) > 1:
            for _next_cat in main_cat_candidates[1:4]:
                _rd = result.get("data", {}) if isinstance(result, dict) else {}
                _rr = _rd.get("result", {}) if isinstance(_rd, dict) else {}
                if not isinstance(_rr, dict):
                    break
                _rc = str(_rr.get("resultCode", "") or "")
                if not _rc or _rc in ("00", "SUCCESS"):
                    break  # 이미 성공 — 재시도 불필요
                _rmsg = _rr.get("resultDesc", "") or _rr.get("resultMessage", "") or ""
                _is_cat_reject = ("전시" in _rmsg and "할 수 없" in _rmsg) or (
                    "잘못된 카테고리" in _rmsg
                )
                if not _is_cat_reject:
                    break  # 카테고리 거부가 아니면 중단
                logger.warning(
                    f"[SSG] 6005 전시카테고리 거부({main_category_id}) → "
                    f"차순위 후보 재시도: {_next_cat}"
                )
                main_category_id = _next_cat
                try:
                    data = client.transform_product(
                        product,
                        category_id,
                        std_category_id=std_category_id,
                        main_category_id=main_category_id,
                        infra=infra,
                        margin_rate=margin_rate,
                        shpp_rqrm_dcnt=shpp_rqrm_dcnt,
                        day_max_qty=day_max_qty,
                        once_min_qty=once_min_qty,
                        once_max_qty=once_max_qty,
                        brand_mappings=brand_mappings,
                    )
                    result = await client.register_product(data)
                except Exception as e:
                    import traceback as _tb

                    logger.error(
                        f"[SSG] 6005 카테고리 재시도 실패: {e}\n{_tb.format_exc()}"
                    )
                    break

        # SSG API 응답 검증
        result_data = result.get("data", {})
        if isinstance(result_data, dict):
            res = result_data.get("result", {})
            if isinstance(res, dict):
                code = res.get("resultCode", "")
                if code and str(code) != "00" and str(code) != "SUCCESS":
                    # resultDesc에 상세 에러 포함 — resultMessage("FAIL")보다 우선
                    msg = (
                        res.get("resultDesc", "")
                        or res.get("resultMessage", "")
                        or f"resultCode={code}"
                    )
                    # 동일 상품 이미 존재 — 첫 전송 성공 후 transmitting stuck으로 itemId 미저장된 경우.
                    # registered_accounts 복구 + "__exists__" 마커로 중복 재등록 차단.
                    if "동일한 상품이 이미 존재" in msg and not existing_no:
                        logger.warning(
                            f"[SSG] 동일상품 존재 오류 → 이미 등록된 것으로 처리 (itemId 수동 확인 필요): "
                            f"product={product.get('id')}"
                        )
                        return {
                            "success": True,
                            "message": "SSG 이미 등록된 상품 (itemId 미확인 — 셀러센터에서 확인 필요)",
                            "_already_exists": True,
                            "data": result_data,
                        }
                    return {
                        "success": False,
                        "message": f"SSG 등록 실패: {msg}",
                        "data": result_data,
                    }

        action = "수정" if existing_no else "등록"
        _ret = {"success": True, "message": f"SSG {action} 성공", "data": result}
        # 멱등가드/수정 경로 — itemId 를 결과에 실어 market_product_nos 백필 보장(#321).
        # (선제검색으로 찾은 itemId 는 DB 미저장 상태이므로 명시 전달 필요)
        if existing_no:
            _ret["product_no"] = existing_no
        return _ret
