"""네이버스토어 단일 상품 상세 조회용 subprocess 스크립트.

현재는 확장앱 탭 컨텍스트 fetch로 상세 수집을 수행하므로 직접 호출하지 않지만,
향후 브라우저 없는 환경(스케줄러/CI)에서 상세 재수집 폴백 경로로 쓰기 위해 보존.
"""

from __future__ import annotations

SUBPROCESS_DETAIL_SCRIPT = r"""
import json, re, sys
from datetime import datetime, timezone

LOG = lambda msg: print(f"[DETAIL-SUB] {msg}", file=sys.stderr, flush=True)

product_url_or_id = sys.argv[1]
channel_uid_hint = sys.argv[2] if len(sys.argv) > 2 else ""
cookies = sys.argv[3] if len(sys.argv) > 3 else ""
proxy_url = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else ""

BASE_URL = "https://smartstore.naver.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": BASE_URL + "/",
}
if cookies:
    HEADERS["Cookie"] = cookies

# URL에서 store_name, product_id 추출
m = re.search(r"(?:smartstore|brand)\.naver\.com/([^/?#]+)/products/(\d+)", product_url_or_id)
store_name = m.group(1) if m else ""
product_id = m.group(2) if m else product_url_or_id
channel_uid = channel_uid_hint

LOG(f"pid={product_id}, store={store_name}, channel={channel_uid or '?'}")

from curl_cffi.requests import Session
# 쿠키 유무와 무관하게 프록시 사용 — Cloud Run 공용 IP 노출 시 429 차단 발생
proxies = {"https": proxy_url, "http": proxy_url} if proxy_url else None

def parse_channel_uid(html):
    m = re.search(r'"channelUid"\s*:\s*"([a-zA-Z0-9]{15,30})"', html)
    return m.group(1) if m else None

try:
    with Session(timeout=20, proxies=proxies, impersonate="chrome") as sess:
        # channelUid 없으면 HTML에서 추출
        if not channel_uid and store_name:
            html_hdrs = {k: v for k, v in HEADERS.items() if k != "Accept"}
            html_hdrs["Accept"] = "text/html,*/*;q=0.8"
            r = sess.get(f"{BASE_URL}/{store_name}", headers=html_hdrs)
            if r.status_code == 200:
                channel_uid = parse_channel_uid(r.text) or ""
            LOG(f"channelUid 추출: {channel_uid}")

        if not channel_uid:
            print(json.dumps({"error": "channelUid 추출 실패"}))
            sys.exit(0)

        # 내부 JSON API(/i/v2/.../products/{id})는 실사용자 브라우저가 아니면
        # 모두 HTTP 429 차단됨. 대신 상품 상세 HTML 페이지를 가져와 내장 JSON 파싱.
        html_url = f"{BASE_URL}/{store_name}/products/{product_id}"
        html_hdrs = {
            "User-Agent": HEADERS["User-Agent"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "Referer": f"{BASE_URL}/{store_name}",
        }
        if cookies:
            html_hdrs["Cookie"] = cookies
        LOG(f"HTML 호출: {html_url}")
        resp = sess.get(html_url, headers=html_hdrs)
        LOG(f"HTTP {resp.status_code} len={len(resp.text)}")
        if resp.status_code != 200:
            print(json.dumps({"error": f"HTTP {resp.status_code}"}))
            sys.exit(0)

        html = resp.text
        d = None
        # 1) window.__PRELOADED_STATE__ 또는 유사 패턴
        patterns = [
            r'window\.__PRELOADED_STATE__\s*=\s*(\{.+?\})\s*;?\s*</script>',
            r'window\.__APOLLO_STATE__\s*=\s*(\{.+?\})\s*;?\s*</script>',
            r'<script id="__NEXT_DATA__"[^>]*>(\{.+?\})</script>',
        ]
        preloaded = None
        for pat in patterns:
            m = re.search(pat, html, re.DOTALL)
            if m:
                try:
                    preloaded = json.loads(m.group(1))
                    LOG(f"PRELOADED_STATE 매칭 ({pat[:30]}...) 파싱 성공")
                    break
                except Exception as pe:
                    LOG(f"패턴 파싱 실패 ({pat[:30]}...): {pe}")

        if preloaded:
            # 최상위 어딘가에 product 객체가 있음 — 재귀 탐색
            def _find_product(obj):
                if isinstance(obj, dict):
                    # id + name + salePrice 조합 있으면 상품 객체로 간주
                    if (obj.get("id") or obj.get("productNo")) and obj.get("name") and (
                        obj.get("salePrice") or obj.get("benefitsView")
                    ):
                        return obj
                    for v in obj.values():
                        r = _find_product(v)
                        if r:
                            return r
                elif isinstance(obj, list):
                    for v in obj:
                        r = _find_product(v)
                        if r:
                            return r
                return None
            d = _find_product(preloaded)
            LOG(f"product 객체 탐색: {'성공' if d else '실패'}")

        # 2) 폴백 — JSON-LD (제한적이지만 이미지/이름은 가능)
        if not d:
            jld_matches = re.findall(
                r'<script type="application/ld\+json">\s*(\{.+?\})\s*</script>',
                html, re.DOTALL,
            )
            for jld in jld_matches:
                try:
                    obj = json.loads(jld)
                    if obj.get("@type") == "Product":
                        # 최소 필드만 수동 매핑
                        d = {
                            "id": product_id,
                            "name": obj.get("name", ""),
                            "salePrice": 0,
                            "productImages": [
                                {"url": u, "imageType": "REPRESENTATIVE"}
                                for u in (
                                    obj.get("image", [])
                                    if isinstance(obj.get("image"), list)
                                    else [obj.get("image")]
                                    if obj.get("image")
                                    else []
                                )
                            ],
                        }
                        LOG("JSON-LD 폴백 사용")
                        break
                except Exception:
                    continue

        if not d:
            LOG("상품 데이터 추출 실패 — HTML 첫 500자 로그")
            LOG(html[:500])
            print(json.dumps({"error": "상품 데이터 추출 실패"}))
            sys.exit(0)
        name = d.get("name") or d.get("dispName", "")

        # 이미지
        rep_imgs, opt_imgs = [], []
        for img in (d.get("productImages") or []):
            url = img.get("url", "")
            if not url:
                continue
            t = img.get("imageType", "")
            if t == "REPRESENTATIVE":
                rep_imgs.append(url)
            elif t == "OPTIONAL":
                opt_imgs.append(url)
        thumbnail = rep_imgs[0] if rep_imgs else ""

        # 상세 HTML에서 이미지 추출
        detail_html = d.get("detailContents", {}).get("detailContentText", "") if isinstance(d.get("detailContents"), dict) else ""
        _detail_extracted = []
        if detail_html:
            _detail_extracted = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', detail_html)
            _detail_extracted = [u for u in _detail_extracted if u.startswith("http")]

        # images: 대표 + 추가
        # detail_images: 상세HTML URL 원본 그대로 (dedup X) + padding
        # - worker.py(2101)는 len(detail_images) > len(images) 일 때만 detail_images 유지
        # - cafe24 markets 플러그인은 set(detail_images) 문자열 매칭으로 images 필터링
        # → 양말 등 상세 HTML 짧은 상품도 덮어쓰기 방지하려면 padding 필요
        # → padding URL은 cafe24 _is_allowed_image 필터에 자연 차단돼 상세페이지에 렌더되지 않음
        images = rep_imgs + opt_imgs
        detail_imgs: list[str] = list(_detail_extracted)
        _pad_needed = max(0, len(images) + 1 - len(detail_imgs))
        if _pad_needed > 0:
            detail_imgs.extend([
                f"https://samba-naver-pad-{i}.internal/p.jpg" for i in range(_pad_needed)
            ])

        # 가격/할인
        sale_price = d.get("salePrice", 0)
        benefits = d.get("benefitsView") or {}
        disc_price = benefits.get("discountedSalePrice", 0) or sale_price
        disc_rate = benefits.get("discountedRatio", 0)

        # 카테고리
        cat_info = d.get("category") or {}
        cat_str = cat_info.get("wholeCategoryName", "") if isinstance(cat_info, dict) else ""
        cat_parts = cat_str.split(">") if cat_str else []
        cat1 = cat_parts[0].strip() if len(cat_parts) > 0 else ""
        cat2 = cat_parts[1].strip() if len(cat_parts) > 1 else ""
        cat3 = cat_parts[2].strip() if len(cat_parts) > 2 else ""
        cat4 = cat_parts[3].strip() if len(cat_parts) > 3 else ""

        # 브랜드/제조사
        search_info = d.get("naverShoppingSearchInfo") or {}
        brand = search_info.get("brandName", "")
        manufacturer = search_info.get("manufacturerName", "")
        model_number = search_info.get("modelName", "") or search_info.get("modelNumber", "")

        # 원산지
        origin_info = d.get("originAreaInfo") or {}
        origin = origin_info.get("content", "") if isinstance(origin_info, dict) else ""

        # 상품정보고시 — 재질/색상/성별/시즌/품번 추출
        # 실제 구조: productInfoProvidedNoticeView 아래에 여러 형태 공존
        #  - dict 형태: {key: value} (레거시)
        #  - 배열 형태: [{"title": "주요소재", "content": "캔버스"}, ...]
        #  - 중첩 dict: {"productInfoProvidedNoticeContent": {"content": [...]}}
        # 모든 형태 순회하며 title/key + content/value 쌍 수집
        material = ""
        color = ""
        sex = ""
        season = ""

        def _collect_notice_pairs(obj, out):
            # 재귀적으로 title/content 또는 key/value 쌍 수집
            if isinstance(obj, list):
                for item in obj:
                    _collect_notice_pairs(item, out)
            elif isinstance(obj, dict):
                title = obj.get("title") or obj.get("name") or obj.get("label")
                content = obj.get("content") or obj.get("value") or obj.get("text")
                if isinstance(title, str) and isinstance(content, (str, int, float)):
                    out.append((title, str(content)))
                    return
                for k, v in obj.items():
                    if isinstance(v, (dict, list)):
                        _collect_notice_pairs(v, out)
                    elif isinstance(v, (str, int, float)):
                        out.append((str(k), str(v)))

        notice = d.get("productInfoProvidedNoticeView") or {}
        pairs = []
        _collect_notice_pairs(notice, pairs)
        # 첫 실행 시 실제 구조 로그 (진단용)
        LOG(f"notice 최상위 키: {list(notice.keys()) if isinstance(notice, dict) else type(notice).__name__}")
        LOG(f"notice pairs 추출: {len(pairs)}건, 샘플={pairs[:5]}")

        for k, v in pairs:
            k_low = str(k).lower()
            v_str = str(v).strip() if v else ""
            if not v_str or v_str in ("해당없음", "상세설명참조", "상세페이지참조"):
                continue
            if "재질" in k_low or "material" in k_low or "소재" in k_low:
                material = material or v_str
            elif "색상" in k_low or "color" in k_low:
                color = color or v_str
            elif "성별" in k_low or "sex" in k_low:
                sex = sex or v_str
            elif "시즌" in k_low or "season" in k_low or "계절" in k_low:
                season = season or v_str
            elif "품번" in k_low or "model" in k_low:
                model_number = model_number or v_str
            elif "원산지" in k_low or "제조국" in k_low:
                origin = origin or v_str

        # 성별/시즌 기본값
        if not sex:
            sex = "남녀공용"
        if not season:
            season = "사계절"

        # 옵션 조합 (worker가 기대하는 options 배열)
        # 진단: 응답에 옵션 관련 키가 실제 있는지 확인
        _opt_keys = [k for k in d.keys() if "option" in k.lower() or "Option" in k]
        LOG(f"옵션 관련 키: {_opt_keys}, optionCombinations건수={len(d.get('optionCombinations') or [])}")
        opt_groups = d.get("options") or []
        group_names = [g.get("groupName", "") for g in opt_groups if isinstance(g, dict)]
        options_list = []
        for combo in (d.get("optionCombinations") or []):
            if not isinstance(combo, dict):
                continue
            opt_names = []
            for i in range(1, 4):
                val = combo.get(f"optionName{i}", "")
                if val:
                    opt_names.append(str(val))
            display = " / ".join(opt_names)
            stock = _clamp_stock(combo.get("stockQuantity", 0))
            options_list.append({
                "name": display,
                "price": combo.get("price", 0) or 0,
                "stock": stock,
                "isSoldOut": stock <= 0,
            })

        # 배송비
        delivery_info = d.get("productDeliveryInfo") or {}
        fee_type = delivery_info.get("deliveryFeeType", "")
        free_ship = fee_type == "FREE"
        shipping_fee = delivery_info.get("baseFee", 0) or 0

        # 재고
        stock_qty = _clamp_stock(d.get("stockQuantity", 0))
        is_sold_out = (d.get("productStatusType", "") != "SALE") or (stock_qty <= 0 and not options_list)

        result = {
            "site_product_id": str(d.get("id", product_id)),
            "siteProductId": str(d.get("id", product_id)),
            "name": name,
            "brand": brand,
            "manufacturer": manufacturer,
            "model_number": model_number,
            "original_price": sale_price,
            "originalPrice": sale_price,
            "sale_price": disc_price,
            "salePrice": disc_price,
            "discount_rate": disc_rate,
            "stock_quantity": stock_qty,
            "stockQuantity": stock_qty,
            "isSoldOut": is_sold_out,
            "is_sold_out": is_sold_out,
            "thumbnail_image_url": thumbnail,
            "thumbnailImageUrl": thumbnail,
            "images": images,
            "detail_images": detail_imgs,
            "detail_html": detail_html,
            "category": cat_str,
            "category1": cat1,
            "category2": cat2,
            "category3": cat3,
            "category4": cat4,
            "origin": origin,
            "material": material,
            "color": color,
            "sex": sex,
            "season": season,
            "options": options_list,
            "optionCombinations": options_list,
            "free_shipping": free_ship,
            "shipping_fee": shipping_fee,
            "source_url": f"{BASE_URL}/{store_name}/products/{d.get('id', product_id)}" if store_name else "",
        }
        LOG(f"완료: name='{name[:30]}' images={len(images)} detailImgs={len(detail_imgs)} options={len(options_list)} origin='{origin}' sex='{sex}' material='{material[:20]}' color='{color[:20]}'")
        print(json.dumps(result, ensure_ascii=False))

except Exception as e:
    LOG(f"예외: {e}")
    import traceback
    traceback.print_exc(file=sys.stderr)
    print(json.dumps({"error": str(e)}))
    sys.exit(0)
"""
