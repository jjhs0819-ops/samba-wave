"""네이버스토어 목록 수집용 subprocess 스크립트.

별도 프로세스에서 curl_cffi 실행 — SQLAlchemy greenlet 충돌 원천 차단.
메인 클래스(NaverStoreSourcingClient)가 이 스크립트를 subprocess로 실행한다.
"""

from __future__ import annotations

SUBPROCESS_COLLECT_SCRIPT = r"""
import json, math, re, sys, time
from datetime import datetime, timezone

LOG = lambda msg: print(f"[SUBPROCESS] {msg}", file=sys.stderr, flush=True)

def _clamp_stock(v):
    # 네이버 9999(충분) placeholder는 99로 제한, 실재고/품절은 유지
    try:
        n = int(v or 0)
    except (TypeError, ValueError):
        return 0
    return 99 if n >= 999 else n

store_url = sys.argv[1]
max_count = int(sys.argv[2])
proxy_url = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else ""

LOG(f"store_url={store_url}, max_count={max_count}, proxy={'Y' if proxy_url else 'N'}")

BASE_URL = "https://smartstore.naver.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://smartstore.naver.com/",
}
HTML_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

def extract_store_name(url):
    m = re.search(r"smartstore\.naver\.com/([^/?#]+)", url)
    return m.group(1) if m else None

def extract_category_id(url):
    m = re.search(r"/category/(\w{8,})", url)
    return m.group(1) if m else None

def parse_channel_uid(html):
    m = re.search(r'"channelUid"\s*:\s*"([a-zA-Z0-9]{15,30})"', html)
    return m.group(1) if m else None

store_name = extract_store_name(store_url) or ""
category_id = extract_category_id(store_url) or "ALL"
page_size = 40
pages_needed = math.ceil(max_count / page_size)
now_iso = datetime.now(tz=timezone.utc).isoformat()

LOG(f"store_name={store_name}, category_id={category_id}, pages_needed={pages_needed}")

from curl_cffi.requests import Session
proxies = {"https": proxy_url, "http": proxy_url} if proxy_url else None

all_products = []
total_in_store = 0

try:
    with Session(timeout=20, proxies=proxies, impersonate="chrome") as sess:
        # channelUid
        page_url = f"{BASE_URL}/{store_name}"
        LOG(f"channelUid 조회: {page_url}")
        resp = sess.get(page_url, headers=HTML_HEADERS)
        LOG(f"channelUid 페이지 HTTP {resp.status_code}, len={len(resp.text)}")
        channel_uid = parse_channel_uid(resp.text) if resp.status_code == 200 else None
        LOG(f"channelUid={channel_uid}")

        if not channel_uid:
            LOG("channelUid 추출 실패 — 종료")
            print(json.dumps({"products": [], "total": 0, "error": "channelUid 추출 실패"}))
            sys.exit(0)

        # 해시 카테고리(32자)는 /categories/{id}/products 엔드포인트가 0건 반환
        # 대신 카테고리 메타 엔드포인트(mappingContent)에서 상품 ID 리스트 획득 후
        # 각 ID마다 상세 API 호출하여 데이터 채움
        is_hash_cat = category_id != "ALL" and len(category_id) >= 20

        def _push_product(pid, name, sale_price, disc_price, disc_rate, thumb,
                          cat_str, cat_id_val, brand, manuf,
                          review_cnt, review_score, free_deliv, option_usable,
                          product_images=None):
            # worker 파이프라인 호환: images 배열 + 카테고리 파싱
            # productImages(REP+OPT 전체)가 있으면 우선 사용, 없으면 썸네일 1장 fallback
            imgs_list = []
            if product_images:
                rep = [img.get("url", "") for img in product_images
                       if img.get("imageType") == "REPRESENTATIVE" and img.get("url")]
                opt = [img.get("url", "") for img in product_images
                       if img.get("imageType") == "OPTIONAL" and img.get("url")]
                imgs_list = rep + opt
            if not imgs_list and thumb:
                imgs_list = [thumb]
            cat_parts = cat_str.split(">") if cat_str else []
            cat1 = cat_parts[0].strip() if len(cat_parts) > 0 else ""
            cat2 = cat_parts[1].strip() if len(cat_parts) > 1 else ""
            cat3 = cat_parts[2].strip() if len(cat_parts) > 2 else ""
            cat4 = cat_parts[3].strip() if len(cat_parts) > 3 else ""
            all_products.append({
                "site_product_id": str(pid),
                "name": name,
                "brand": brand,
                "manufacturer": manuf,
                "original_price": sale_price,
                "sale_price": disc_price,
                "discount_rate": disc_rate,
                "thumbnail_image_url": thumb,
                "images": imgs_list,
                "category": cat_str,
                "category1": cat1,
                "category2": cat2,
                "category3": cat3,
                "category4": cat4,
                "category_id": cat_id_val,
                "review_count": review_cnt,
                "review_score": review_score,
                "free_delivery": free_deliv,
                "option_usable": option_usable,
                "store_name": store_name,
                "channel_uid": channel_uid,
                "source_site": "NAVERSTORE",
                "source_url": f"{BASE_URL}/{store_name}/products/{pid}",
                "collected_at": now_iso,
            })

        if is_hash_cat:
            # Plan B: HTML SSR 직접 파싱 — detail API 지속 429 회피 (UUID 카테고리 대응)
            # Why: coming 등 UUID 카테고리는 mappingContent 메타/detail API가 0건 또는
            # 지속 429 반환. 2026-04-18 진단 로그에서 확인: HTML(2.3MB)의 data-shp-area="list.pd"
            # 슬롯에 data-shp-contents-id(ID) + data-shp-contents-dtl(JSON: chnl_prod_nm=이름,
            # price=가격, exhibition_category=카테고리ID) 임베디드. swiper 슬라이드 내
            # shop-phinf.pstatic.net img URL도 함께 SSR됨. detail API 없이 HTML만으로 수집 가능.
            import html as html_lib

            def _fetch_html_products(page):
                html_url = f"{BASE_URL}/{store_name}/category/{category_id}?cp={page}"
                LOG(f"HTML 전체 파싱: cp={page}")
                r2 = sess.get(html_url, headers=HTML_HEADERS)
                if r2.status_code != 200:
                    LOG(f"HTML 실패 status={r2.status_code} cp={page}")
                    return []
                html_text = r2.text
                LOG(f"HTML cp={page}: length={len(html_text)}")

                area_positions = [
                    m.start() for m in re.finditer(r'data-shp-area="list\.pd"', html_text)
                ]
                LOG(f"HTML cp={page}: list.pd 슬롯={len(area_positions)}개")

                # 상품ID → brandName 매핑 사전 구축 (__PRELOADED_STATE__ JSON 활용)
                # Why: brandName은 naverShoppingSearchInfo 중첩 오브젝트 내부에 있어
                # 단일 object 내 [^{}] 매칭은 불가 (중간 '{' 존재).
                # 대신 상품 id 위치부터 다음 상품 id 전까지 범위에서 brandName 탐색.
                # 상품 id는 항상 10자 이상 숫자 (brandId 3~4자 / channelId 문자혼합 등과 구분).
                brand_map: dict = {}
                id_iter = list(re.finditer(r'"id"\s*:\s*"?(\d{10,})"?\s*,', html_text))
                for idx, m in enumerate(id_iter):
                    pid_b = m.group(1)
                    if pid_b in brand_map:
                        continue
                    scope_start = m.end()
                    scope_end = (
                        id_iter[idx + 1].start()
                        if idx + 1 < len(id_iter)
                        else scope_start + 12000
                    )
                    scope = html_text[scope_start:scope_end]
                    b_m = re.search(r'"brandName"\s*:\s*"([^"]*)"', scope)
                    if b_m and b_m.group(1):
                        brand_map[pid_b] = b_m.group(1)
                LOG(
                    f"HTML cp={page}: brand_map={len(brand_map)}개 "
                    f"샘플={dict(list(brand_map.items())[:3])}"
                )

                products: list = []
                seen_ids: set = set()
                for pos in area_positions:
                    # 슬롯당 8000자 — 속성 + 중첩 swiper-slide + img 태그 커버
                    chunk = html_text[pos: pos + 8000]
                    if 'data-shp-contents-type="chnl_prod_no"' not in chunk:
                        continue
                    id_m = re.search(r'data-shp-contents-id="(\d+)"', chunk)
                    if not id_m:
                        continue
                    pid = id_m.group(1)
                    if pid in seen_ids:
                        continue
                    seen_ids.add(pid)

                    # data-shp-contents-dtl JSON 파싱 (HTML 엔티티 디코드 필수)
                    dtl_m = re.search(r'data-shp-contents-dtl="([^"]+)"', chunk)
                    name = ""
                    price = 0
                    exhibition_cat = ""
                    if dtl_m:
                        try:
                            dtl_list = json.loads(html_lib.unescape(dtl_m.group(1)))
                            for kv in dtl_list:
                                k = kv.get("key", "")
                                v = kv.get("value", "")
                                if k == "chnl_prod_nm":
                                    name = v or ""
                                elif k == "price":
                                    try:
                                        price = int(v) if v else 0
                                    except (TypeError, ValueError):
                                        price = 0
                                elif k == "exhibition_category":
                                    exhibition_cat = str(v or "")
                        except (json.JSONDecodeError, TypeError, ValueError) as _je:
                            LOG(f"dtl JSON 파싱 실패 pid={pid}: {_je}")
                    if not name:
                        continue

                    # 썸네일 추출 — naver CDN 우선, fallback 확장자 매칭
                    img_m = re.search(
                        r'(?:src|data-src)="(https://[^"]*phinf\.pstatic\.net/[^"]+)"',
                        chunk,
                    )
                    if not img_m:
                        img_m = re.search(
                            r'(?:src|data-src)="(https://[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
                            chunk,
                        )
                    thumb = img_m.group(1) if img_m else ""

                    products.append({
                        "pid": pid,
                        "name": name,
                        "price": price,
                        "thumb": thumb,
                        "exhibition_cat": exhibition_cat,
                        "brand": brand_map.get(pid, ""),
                    })

                LOG(f"HTML cp={page}: {len(products)}개 상품 추출")
                return products

            pages_total = max(pages_needed, 1)
            for cp in range(1, pages_total + 1):
                if cp > 1:
                    time.sleep(1.0)
                page_products = _fetch_html_products(cp)
                if not page_products:
                    LOG(f"cp={cp}: 상품 없음 — 수집 종료")
                    break
                for p in page_products:
                    if len(all_products) >= max_count:
                        break
                    _push_product(
                        pid=p["pid"],
                        name=p["name"],
                        sale_price=p["price"],
                        disc_price=p["price"],
                        disc_rate=0,
                        thumb=p["thumb"],
                        cat_str="",
                        cat_id_val=p["exhibition_cat"],
                        brand=p.get("brand", ""),
                        manuf=p.get("brand", ""),
                        review_cnt=0,
                        review_score=0,
                        free_deliv=False,
                        option_usable=False,
                        product_images=None,
                    )
                if len(all_products) >= max_count:
                    break

            total_in_store = len(all_products)
            LOG(f"해시 카테고리 HTML 수집 완료: {len(all_products)}개")

        else:
            # ALL(전체) — 기존 페이지네이션 로직
            for page_num in range(1, pages_needed + 1):
                if page_num > 1:
                    time.sleep(2.0)

                api_url = (
                    f"{BASE_URL}/i/v2/channels/{channel_uid}"
                    f"/categories/{category_id}/products"
                    f"?categorySearchType=STDCATG&sortType=POPULAR"
                    f"&page={page_num}&pageSize={page_size}"
                    f"&deduplicateGroupEpId=true"
                )
                req_headers = {
                    **HEADERS,
                    "Referer": f"{BASE_URL}/{store_name}/category/{category_id}",
                }
                LOG(f"목록 API 호출: page={page_num}/{pages_needed}")
                resp = sess.get(api_url, headers=req_headers)
                LOG(f"목록 API HTTP {resp.status_code}")
                if resp.status_code != 200:
                    LOG(f"HTTP 에러 → 중단. body={resp.text[:200]}")
                    break

                data = resp.json()
                raw_products = data.get("simpleProducts", [])
                if page_num == 1:
                    total_in_store = data.get("totalCount", 0)
                LOG(f"page={page_num}: simpleProducts={len(raw_products)}, totalCount={total_in_store}")
                if not raw_products:
                    break

                for raw in raw_products:
                    pid = raw.get("id")
                    name = raw.get("name") or raw.get("dispName", "")
                    if not pid or not name:
                        continue
                    sale_price = raw.get("salePrice", 0)
                    benefits = raw.get("benefitsView", {})
                    disc_price = benefits.get("discountedSalePrice", 0) or sale_price
                    disc_rate = benefits.get("discountedRatio", 0)
                    cat_info = raw.get("category", {})
                    cat_str = ""
                    if isinstance(cat_info, dict):
                        cat_str = cat_info.get("wholeCategoryName", "") or cat_info.get("categoryName", "")
                    search_info = raw.get("naverShoppingSearchInfo", {})
                    thumb = raw.get("representativeImageUrl", "")
                    review_info = raw.get("reviewAmount", {})
                    delivery_info = raw.get("productDeliveryInfo", {})
                    # 상세 API 호출 — productImages(REP+OPT 전체) 획득
                    # 목록 API(simpleProducts)는 대표이미지만 주므로 추가 이미지를 얻으려면 상세 호출 필수
                    product_images = []
                    try:
                        time.sleep(0.3)
                        d_url = (
                            f"{BASE_URL}/i/v2/channels/{channel_uid}"
                            f"/products/{pid}?withWindow=false"
                        )
                        d_resp = sess.get(
                            d_url,
                            headers={**HEADERS, "Referer": f"{BASE_URL}/{store_name}/products/{pid}"},
                        )
                        if d_resp.status_code == 200:
                            product_images = d_resp.json().get("productImages") or []
                    except Exception as _de:
                        LOG(f"상세 이미지 조회 실패 pid={pid}: {_de}")
                    _push_product(
                        pid=pid, name=name, sale_price=sale_price,
                        disc_price=disc_price, disc_rate=disc_rate, thumb=thumb,
                        cat_str=cat_str,
                        cat_id_val=cat_info.get("categoryId", "") if isinstance(cat_info, dict) else "",
                        brand=search_info.get("brandName", ""),
                        manuf=search_info.get("manufacturerName", ""),
                        review_cnt=review_info.get("totalReviewCount", 0),
                        review_score=review_info.get("averageReviewScore", 0),
                        free_deliv=delivery_info.get("deliveryFeeType", "") == "FREE",
                        option_usable=raw.get("optionUsable", False),
                        product_images=product_images,
                    )

                if len(all_products) >= max_count:
                    all_products = all_products[:max_count]
                    break
                if len(raw_products) < page_size:
                    break

except Exception as e:
    LOG(f"예외 발생: {e}")
    import traceback
    traceback.print_exc(file=sys.stderr)
    print(json.dumps({"products": [], "total": 0, "error": str(e)}), file=sys.stdout)
    sys.exit(0)

LOG(f"완료: {len(all_products)}개 수집 (전체 {total_in_store}개)")
print(json.dumps({"products": all_products, "total": total_in_store, "channelUid": channel_uid, "storeName": store_name}))
"""
