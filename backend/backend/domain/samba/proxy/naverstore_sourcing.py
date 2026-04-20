"""네이버스토어 소싱용 클라이언트 — 내부 JSON API 기반.

스마트스토어 내부 API를 직접 호출하여 상품 목록/상세를 수집한다.
curl_cffi를 사용하여 TLS fingerprint를 브라우저처럼 위장한다.
worker 컨텍스트에서는 동기 Session + asyncio.to_thread로 greenlet 충돌 회피.

핵심 API:
  - 상품 목록: GET /i/v2/channels/{channelUid}/categories/ALL/products?page=1&pageSize=40
  - 상품 상세: GET /i/v2/channels/{channelUid}/products/{productId}?withWindow=false
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from backend.utils.logger import logger


def _clamp_stock(v: Any) -> int:
    """네이버 consumer API의 9999(무한) placeholder를 99로 제한.

    Why: 네이버는 재고 '충분' 상태를 9999로 반환하지만 쌈바 UI/마켓 전송은 99로 표현.
    How to apply: 실재고(1~998) 및 품절(0)은 그대로 유지, 999 이상만 99로 클램프.
    """
    try:
        n = int(v or 0)
    except (TypeError, ValueError):
        return 0
    return 99 if n >= 999 else n


# ------------------------------------------------------------------
# subprocess 수집 스크립트 — 별도 프로세스에서 curl_cffi 실행
# SQLAlchemy greenlet과 충돌을 원천 차단하기 위해 프로세스 격리
# ------------------------------------------------------------------
_SUBPROCESS_COLLECT_SCRIPT = r"""
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


# ------------------------------------------------------------------
# subprocess 상세 조회 스크립트 — 단일 상품 상세 데이터 획득
# ------------------------------------------------------------------
_SUBPROCESS_DETAIL_SCRIPT = r"""
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
    m = re.search(r'"channelUid"\\s*:\\s*"([a-zA-Z0-9]{15,30})"', html)
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


def _parse_detail_product(
    d: dict[str, Any], product_id: str, store_name: str
) -> dict[str, Any]:
    """상세 API 응답(product 객체)을 worker 호환 snake_case 스키마로 파싱.

    확장앱이 탭 컨텍스트에서 /i/v2/channels/{uid}/products/{pid} API로 가져온 raw JSON을
    받아 표준 상품 필드로 변환한다. subprocess 스크립트의 파싱 로직과 동치.
    """
    BASE_URL = "https://smartstore.naver.com"
    name = d.get("name") or d.get("dispName", "")

    rep_imgs: list[str] = []
    opt_imgs: list[str] = []
    for img in d.get("productImages") or []:
        url = img.get("url", "")
        if not url:
            continue
        t = img.get("imageType", "")
        if t == "REPRESENTATIVE":
            rep_imgs.append(url)
        elif t == "OPTIONAL":
            opt_imgs.append(url)
    thumbnail = rep_imgs[0] if rep_imgs else ""

    detail_html = ""
    dc = d.get("detailContents")
    if isinstance(dc, dict):
        detail_html = dc.get("detailContentText", "") or ""
    _detail_extracted: list[str] = []
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
        detail_imgs.extend(
            [f"https://samba-naver-pad-{i}.internal/p.jpg" for i in range(_pad_needed)]
        )

    sale_price = d.get("salePrice", 0) or 0
    benefits = d.get("benefitsView") or {}
    disc_price = benefits.get("discountedSalePrice", 0) or sale_price
    disc_rate = benefits.get("discountedRatio", 0) or 0

    cat_info = d.get("category") or {}
    cat_str = (
        cat_info.get("wholeCategoryName", "") if isinstance(cat_info, dict) else ""
    )
    cat_parts = cat_str.split(">") if cat_str else []
    cat1 = cat_parts[0].strip() if len(cat_parts) > 0 else ""
    cat2 = cat_parts[1].strip() if len(cat_parts) > 1 else ""
    cat3 = cat_parts[2].strip() if len(cat_parts) > 2 else ""
    cat4 = cat_parts[3].strip() if len(cat_parts) > 3 else ""

    search_info = d.get("naverShoppingSearchInfo") or {}
    brand = search_info.get("brandName", "") or ""
    manufacturer = search_info.get("manufacturerName", "") or ""
    model_number = (
        search_info.get("modelName", "") or search_info.get("modelNumber", "") or ""
    )

    origin_info = d.get("originAreaInfo") or {}
    origin = origin_info.get("content", "") if isinstance(origin_info, dict) else ""

    material = ""
    color = ""
    sex = ""
    season = ""

    def _collect_notice_pairs(obj: Any, out: list[tuple[str, str]]) -> None:
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
    pairs: list[tuple[str, str]] = []
    _collect_notice_pairs(notice, pairs)

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

    if not sex:
        sex = "남녀공용"
    if not season:
        season = "사계절"

    options_list: list[dict[str, Any]] = []
    for combo in d.get("optionCombinations") or []:
        if not isinstance(combo, dict):
            continue
        opt_names: list[str] = []
        for i in range(1, 4):
            val = combo.get(f"optionName{i}", "")
            if val:
                opt_names.append(str(val))
        display = " / ".join(opt_names)
        stock = _clamp_stock(combo.get("stockQuantity", 0))
        options_list.append(
            {
                "name": display,
                "price": combo.get("price", 0) or 0,
                "stock": stock,
                "isSoldOut": stock <= 0,
            }
        )

    delivery_info = d.get("productDeliveryInfo") or {}
    fee_type = delivery_info.get("deliveryFeeType", "")
    free_ship = fee_type == "FREE"
    shipping_fee = delivery_info.get("baseFee", 0) or 0

    stock_qty = _clamp_stock(d.get("stockQuantity", 0))
    is_sold_out = (d.get("productStatusType", "") != "SALE") or (
        stock_qty <= 0 and not options_list
    )

    source_url = (
        f"{BASE_URL}/{store_name}/products/{d.get('id', product_id)}"
        if store_name
        else ""
    )

    return {
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
        "source_url": source_url,
    }


def _get_proxy_url() -> str:
    """수집용 프록시 URL 가져오기."""
    try:
        from backend.core.config import settings

        url = settings.collect_proxy_url or ""
        return url.strip()
    except Exception:
        return ""


class NaverStoreSourcingClient:
    """네이버스토어 소싱용 클라이언트.

    내부 JSON API를 활용한 상품 목록/상세 조회를 제공한다.
    curl_cffi로 브라우저 TLS fingerprint를 위장하여 봇 차단을 우회한다.
    """

    BASE_URL = "https://smartstore.naver.com"

    HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/136.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://smartstore.naver.com/",
    }

    HTML_HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/136.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }

    # 계정 쿠키 캐시 (프로세스 생애주기 내 60초)
    _cookies_cache: tuple[str, float] = ("", 0.0)

    @classmethod
    async def _fetch_cookies_from_db(cls) -> str:
        """sourcing_account 테이블에서 NAVERSTORE 활성 계정 쿠키 조회.

        additional_fields JSON 의 'cookies' 키 값 반환. 60초 캐싱.
        """
        import time as _time

        cached_val, cached_at = cls._cookies_cache
        if cached_val and (_time.time() - cached_at) < 60:
            return cached_val

        from backend.db.orm import get_read_session
        from backend.domain.samba.sourcing_account.model import SambaSourcingAccount
        from sqlmodel import select

        async with get_read_session() as session:
            stmt = (
                select(SambaSourcingAccount)
                .where(SambaSourcingAccount.site_name == "NAVERSTORE")
                .where(SambaSourcingAccount.is_active == True)  # noqa: E712
                .order_by(SambaSourcingAccount.updated_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            account = result.scalar_one_or_none()

        cookies = ""
        if account and account.additional_fields:
            af = account.additional_fields
            if isinstance(af, dict):
                cookies = str(af.get("cookies") or "").strip()

        cls._cookies_cache = (cookies, _time.time())
        return cookies

    # 상세 API 요청 간 딜레이 (초) — 429 방지
    DETAIL_DELAY: float = 2.0

    def __init__(self, proxy_url: str | None = None) -> None:
        self._proxy_url = proxy_url or _get_proxy_url()
        self._timeout = 20
        # channelUid 캐시: store_name -> channelUid
        self._uid_cache: dict[str, str] = {}

    def _build_proxies(self) -> dict[str, str] | None:
        """프록시 설정 dict 반환."""
        if self._proxy_url:
            return {"https": self._proxy_url, "http": self._proxy_url}
        return None

    # ------------------------------------------------------------------
    # channelUid 추출
    # ------------------------------------------------------------------

    async def resolve_channel_uid(self, store_url: str) -> Optional[str]:
        """스토어 URL에서 channelUid를 추출한다.

        목록 API를 호출하여 응답에서 channelUid를 추출하는 방식을 우선 시도하고,
        실패 시 HTML 파싱으로 폴백한다.
        """
        store_name = self._extract_store_name(store_url)
        if not store_name:
            logger.error(f"[NAVERSTORE] 스토어명 추출 실패: {store_url}")
            return None

        # 캐시 확인
        if store_name in self._uid_cache:
            return self._uid_cache[store_name]

        # HTML 페이지에서 channelUid 추출
        page_url = f"{self.BASE_URL}/{store_name}"
        logger.info(f"[NAVERSTORE] channelUid 조회: {page_url}")

        try:
            from curl_cffi.requests import AsyncSession

            async with AsyncSession(
                timeout=self._timeout,
                proxies=self._build_proxies(),
                impersonate="chrome",
            ) as session:
                resp = await session.get(page_url, headers=self.HTML_HEADERS)
                if resp.status_code != 200:
                    logger.error(
                        f"[NAVERSTORE] 스토어 페이지 HTTP {resp.status_code}: {store_name}"
                    )
                    return None

                html = resp.text
                channel_uid = self._parse_channel_uid(html)
                if channel_uid:
                    self._uid_cache[store_name] = channel_uid
                    logger.info(
                        f"[NAVERSTORE] channelUid 확인: {store_name} -> {channel_uid}"
                    )
                return channel_uid

        except Exception as e:
            logger.error(f"[NAVERSTORE] channelUid 조회 실패: {store_name} — {e}")
            return None

    def _parse_channel_uid(self, html: str) -> Optional[str]:
        """HTML의 __PRELOADED_STATE__에서 channelUid를 추출."""
        # channelUid 패턴: 영숫자 21자리
        m = re.search(r'"channelUid"\s*:\s*"([a-zA-Z0-9]{15,30})"', html)
        if m:
            return m.group(1)

        # __PRELOADED_STATE__ JSON 파싱 시도
        state_match = re.search(r"window\.__PRELOADED_STATE__\s*=\s*", html)
        if state_match:
            start = state_match.end()
            end = html.find(";</script>", start)
            if end > start:
                raw = html[start:end]
                raw = re.sub(r"\bundefined\b", "null", raw)
                try:
                    decoder = json.JSONDecoder()
                    data, _ = decoder.raw_decode(raw)
                    # channel 정보에서 channelUid 추출
                    channel = data.get("channel", {})
                    if isinstance(channel, dict):
                        uid = channel.get("channelUid")
                        if uid:
                            return uid
                    # simpleProductForDetailPage에서 추출
                    spd = data.get("simpleProductForDetailPage", {}).get("A", {})
                    ch = spd.get("channel", {})
                    if isinstance(ch, dict):
                        uid = ch.get("channelUid")
                        if uid:
                            return uid
                except (json.JSONDecodeError, ValueError):
                    pass

        return None

    # ------------------------------------------------------------------
    # URL → 스토어명/카테고리명 파싱 (UI 표시용)
    # ------------------------------------------------------------------

    async def resolve_url_info(self, store_url: str) -> dict[str, str]:
        """URL에서 스토어명 + 카테고리 표시명 추출.

        Returns:
            {"storeName": "coming", "categoryName": "전체상품" | "스니커즈" | ...}

        우선순위: HTML <title> 파싱 → JSON 스코프 매칭 → 메타 API → fallback.
        title 파싱이 UUID/숫자 카테고리 모두 가장 안정적(리프 카테고리명 추출).
        BBLUE처럼 <title>이 스토어명 단독인 스토어는 JSON 스코프 매칭으로 fallback.
        JSON 스코프에서는 스토어 메뉴 카테고리명(name/categoryName)만 사용 —
        wholeCategoryName은 네이버 표준 카테고리 전체경로라 제외.
        """
        store_name = self._extract_store_name(store_url) or ""
        category_id = self._extract_category_id(store_url)

        # 카테고리 없음 → 전체상품
        if not category_id:
            return {"storeName": store_name, "categoryName": "전체상품"}

        from curl_cffi.requests import AsyncSession

        # HTML 한 번만 받아서 1)/2) 둘 다 시도
        html = ""
        try:
            html_url = f"{self.BASE_URL}/{store_name}/category/{category_id}?cp=1"
            async with AsyncSession(
                timeout=self._timeout,
                proxies=self._build_proxies(),
                impersonate="chrome",
            ) as session:
                r = await session.get(html_url, headers=self.HTML_HEADERS)
                if r.status_code == 200:
                    html = r.text
        except Exception as e:
            logger.warning(f"[NAVERSTORE] HTML fetch 실패: {e}")

        # 1) HTML <title> 파싱 — UUID/숫자 카테고리 모두 가장 안정적
        #    전형 포맷 예: "스니커즈 : gaia2937 - 네이버 스마트스토어"
        title_is_store_only = False
        if html:
            try:
                m = re.search(r"<title>([^<]+)</title>", html)
                if m:
                    title = m.group(1).strip()
                    for sep in [" : ", " - ", " | "]:
                        if sep in title:
                            candidate = title.split(sep)[0].strip()
                            if (
                                candidate
                                and candidate != store_name
                                and "네이버" not in candidate
                                and "스마트스토어" not in candidate
                                and "브랜드스토어" not in candidate
                            ):
                                return {
                                    "storeName": store_name,
                                    "categoryName": candidate,
                                }
                    # 구분자 없고 store_name만 있는 경우 → JSON 스코프 매칭으로 넘김
                    if title.strip() == store_name:
                        title_is_store_only = True
            except Exception as e:
                logger.warning(f"[NAVERSTORE] <title> 파싱 실패: {e}")

        # 2) JSON 스코프 매칭 fallback — BBLUE처럼 title이 스토어명 단독인 케이스
        #    HTML 내 카테고리 정보는 `"name":"...","categoryId":"<id>",...,` 형태.
        #    스토어 메뉴 카테고리명만 추출 (wholeCategoryName은 네이버 표준 카테고리라 제외).
        if html:
            try:
                cid_pattern = rf'"categoryId"\s*:\s*"{re.escape(category_id)}"'
                cat_name = ""
                for m in re.finditer(cid_pattern, html):
                    scope_start = max(0, m.start() - 400)
                    scope_end = min(len(html), m.end() + 400)
                    scope = html[scope_start:scope_end]
                    for field in ("name", "categoryName"):
                        fm = re.search(rf'"{field}"\s*:\s*"([^"]+)"', scope)
                        if fm:
                            raw_name = fm.group(1)
                            try:
                                decoded = json.loads(f'"{raw_name}"')
                            except Exception:
                                decoded = raw_name
                            decoded = decoded.strip()
                            if decoded and decoded != store_name:
                                cat_name = decoded
                                break
                    if cat_name:
                        break
                if cat_name:
                    return {"storeName": store_name, "categoryName": cat_name}
            except Exception as e:
                logger.warning(f"[NAVERSTORE] JSON 스코프 매칭 실패: {e}")

        # title이 스토어명 단독이었고 JSON 스코프도 못 찾으면 "전체상품"
        if title_is_store_only:
            return {"storeName": store_name, "categoryName": "전체상품"}

        # 2) 메타 API fallback
        channel_uid = await self.resolve_channel_uid(store_url)
        if channel_uid:
            meta_url = (
                f"{self.BASE_URL}/i/v2/channels/{channel_uid}"
                f"/categories/{category_id}?categoryDisplayType=DISPLAY"
            )
            referer = f"{self.BASE_URL}/{store_name}/category/{category_id}"
            try:
                async with AsyncSession(
                    timeout=self._timeout,
                    proxies=self._build_proxies(),
                    impersonate="chrome",
                ) as session:
                    resp = await session.get(
                        meta_url,
                        headers={**self.HEADERS, "Referer": referer},
                    )
                    if resp.status_code == 200:
                        data = resp.json() or {}
                        cat_name = (
                            data.get("name")
                            or data.get("displayName")
                            or data.get("categoryName")
                            or data.get("title")
                            or ""
                        )
                        if not cat_name:
                            info = (
                                data.get("categoryInfo") or data.get("category") or {}
                            )
                            if isinstance(info, dict):
                                cat_name = (
                                    info.get("name")
                                    or info.get("displayName")
                                    or info.get("categoryName")
                                    or ""
                                )
                        if cat_name:
                            return {"storeName": store_name, "categoryName": cat_name}
            except Exception as e:
                logger.warning(f"[NAVERSTORE] 메타 API 카테고리명 조회 실패: {e}")

        # 3) 최후 fallback
        return {"storeName": store_name, "categoryName": category_id[:8]}

    # ------------------------------------------------------------------
    # 스토어 상품 목록
    # ------------------------------------------------------------------

    async def get_store_products(
        self,
        store_url: str,
        page: int = 1,
        page_size: int = 40,
        sort_type: str = "POPULAR",
    ) -> dict[str, Any]:
        """스토어 전체 상품 목록 조회.

        Args:
            store_url: 스마트스토어 URL
            page: 페이지 번호 (1부터)
            page_size: 페이지당 상품 수 (기본 40)
            sort_type: 정렬 (POPULAR, RECENT, LOW_PRICE, HIGH_PRICE, REVIEW)

        Returns:
            {
                "products": [...],
                "totalCount": int,
                "page": int,
                "pageSize": int,
                "channelUid": str,
                "storeName": str,
            }
        """
        channel_uid = await self.resolve_channel_uid(store_url)
        if not channel_uid:
            return {
                "products": [],
                "totalCount": 0,
                "error": "channelUid 추출 실패",
            }

        store_name = self._extract_store_name(store_url) or ""
        api_url = (
            f"{self.BASE_URL}/i/v2/channels/{channel_uid}"
            f"/categories/ALL/products"
            f"?categorySearchType=STDCATG"
            f"&sortType={sort_type}"
            f"&page={page}"
            f"&pageSize={page_size}"
            f"&deduplicateGroupEpId=true"
        )

        logger.info(
            f"[NAVERSTORE] 상품 목록 조회: {store_name} (page={page}, size={page_size})"
        )

        try:
            from curl_cffi.requests import AsyncSession

            async with AsyncSession(
                timeout=self._timeout,
                proxies=self._build_proxies(),
                impersonate="chrome",
            ) as session:
                resp = await session.get(
                    api_url,
                    headers={
                        **self.HEADERS,
                        "Referer": f"{self.BASE_URL}/{store_name}",
                    },
                )
                if resp.status_code != 200:
                    logger.error(
                        f"[NAVERSTORE] 상품 목록 HTTP {resp.status_code}: {store_name}"
                    )
                    return {
                        "products": [],
                        "totalCount": 0,
                        "error": f"HTTP {resp.status_code}",
                    }

                data = resp.json()

            raw_products = data.get("simpleProducts", [])
            total_count = data.get("totalCount", 0)
            now_iso = datetime.now(tz=timezone.utc).isoformat()

            products = []
            for raw in raw_products:
                product = self._transform_list_product(
                    raw, channel_uid, store_name, now_iso
                )
                if product:
                    products.append(product)

            logger.info(
                f"[NAVERSTORE] 상품 목록 완료: {store_name} — "
                f"{len(products)}개 (전체 {total_count}개)"
            )

            return {
                "products": products,
                "totalCount": total_count,
                "page": page,
                "pageSize": page_size,
                "channelUid": channel_uid,
                "storeName": store_name,
            }

        except Exception as e:
            logger.error(f"[NAVERSTORE] 상품 목록 실패: {store_name} — {e}")
            return {"products": [], "totalCount": 0, "error": str(e)}

    def _transform_list_product(
        self,
        raw: dict[str, Any],
        channel_uid: str,
        store_name: str,
        now_iso: str,
    ) -> Optional[dict[str, Any]]:
        """목록 API 응답을 표준 상품 dict로 변환."""
        product_id = raw.get("id")
        name = raw.get("name") or raw.get("dispName", "")
        if not product_id or not name:
            return None

        sale_price = raw.get("salePrice", 0)
        benefits = raw.get("benefitsView", {})
        discounted_price = benefits.get("discountedSalePrice", 0) or sale_price
        discount_rate = benefits.get("discountedRatio", 0)

        # 카테고리
        category_info = raw.get("category", {})
        category_str = ""
        if isinstance(category_info, dict):
            category_str = category_info.get("wholeCategoryName", "")
            if not category_str:
                category_str = category_info.get("categoryName", "")

        # 브랜드/제조사
        search_info = raw.get("naverShoppingSearchInfo", {})
        brand = search_info.get("brandName", "")
        manufacturer = search_info.get("manufacturerName", "")

        # 이미지
        thumbnail = raw.get("representativeImageUrl", "")

        # 리뷰
        review_info = raw.get("reviewAmount", {})
        review_count = review_info.get("totalReviewCount", 0)
        review_score = review_info.get("averageReviewScore", 0)

        # 배송
        delivery_info = raw.get("productDeliveryInfo", {})
        delivery_fee_type = delivery_info.get("deliveryFeeType", "")

        return {
            "siteProductId": str(product_id),
            "name": name,
            "brand": brand,
            "manufacturer": manufacturer,
            "originalPrice": sale_price,
            "salePrice": discounted_price,
            "discountRate": discount_rate,
            "thumbnailImageUrl": thumbnail,
            "category": category_str,
            "categoryId": category_info.get("categoryId", ""),
            "reviewCount": review_count,
            "reviewScore": review_score,
            "freeDelivery": delivery_fee_type == "FREE",
            "optionUsable": raw.get("optionUsable", False),
            "storeName": store_name,
            "channelUid": channel_uid,
            "sourceSite": "NAVERSTORE",
            "sourceUrl": (f"{self.BASE_URL}/{store_name}/products/{product_id}"),
            "collectedAt": now_iso,
        }

    async def get_store_products_multi(
        self,
        store_url: str,
        total_count: int = 100,
        page_size: int = 40,
        sort_type: str = "POPULAR",
        page_delay: float = 2.0,
        cookies: Optional[str] = None,
    ) -> dict[str, Any]:
        """멀티페이지 상품 목록 조회 — 하나의 세션에서 여러 페이지를 순회.

        2페이지부터는 쿠키 필요 (네이버 인증 요구).

        Returns:
            {
                "products": [...],
                "totalCount": int (스토어 전체),
                "fetchedCount": int (실제 수집),
                "channelUid": str,
                "storeName": str,
            }
        """
        import math

        channel_uid = await self.resolve_channel_uid(store_url)
        if not channel_uid:
            return {"products": [], "totalCount": 0, "error": "channelUid 추출 실패"}

        store_name = self._extract_store_name(store_url) or ""
        category_id = self._extract_category_id(store_url) or "ALL"
        pages_needed = math.ceil(total_count / page_size)
        all_products: list[dict] = []
        total_in_store = 0
        now_iso = datetime.now(tz=timezone.utc).isoformat()

        logger.info(
            f"[NAVERSTORE] 수집 시작: {store_name} (카테고리={'전체' if category_id == 'ALL' else category_id}, 목표={total_count}개)"
        )

        try:
            from curl_cffi.requests import AsyncSession

            # 쿠키가 있으면 프록시 불필요
            proxies = None if cookies else self._build_proxies()
            async with AsyncSession(
                timeout=self._timeout,
                proxies=proxies,
                impersonate="chrome",
            ) as session:
                for page_num in range(1, pages_needed + 1):
                    if page_num > 1:
                        await asyncio.sleep(page_delay)

                    # 원본 로직(efa38e9b)과 동일: STDCATG 사용
                    api_url = (
                        f"{self.BASE_URL}/i/v2/channels/{channel_uid}"
                        f"/categories/{category_id}/products"
                        f"?categorySearchType=STDCATG"
                        f"&sortType={sort_type}"
                        f"&page={page_num}"
                        f"&pageSize={page_size}"
                        f"&deduplicateGroupEpId=true"
                    )

                    req_headers = {
                        **self.HEADERS,
                        "Referer": f"{self.BASE_URL}/{store_name}/category/{category_id}",
                    }
                    if cookies:
                        req_headers["Cookie"] = cookies

                    logger.info(
                        f"[NAVERSTORE] 상품 목록 조회: {store_name} (page={page_num}, size={page_size}, cookies={'Y' if cookies else 'N'})"
                    )

                    resp = await session.get(api_url, headers=req_headers)

                    if resp.status_code != 200:
                        logger.error(
                            f"[NAVERSTORE] 상품 목록 HTTP {resp.status_code}: {store_name} page={page_num}"
                        )
                        break

                    data = resp.json()
                    raw_products = data.get("simpleProducts", [])

                    logger.info(
                        f"[NAVERSTORE] page={page_num} totalCount={data.get('totalCount')}, "
                        f"simpleProducts={len(raw_products)}"
                    )

                    if page_num == 1:
                        total_in_store = data.get("totalCount", 0)

                    if not raw_products:
                        logger.info(
                            f"[NAVERSTORE] 상품 목록 빈 페이지: page={page_num}"
                        )
                        break

                    for raw in raw_products:
                        product = self._transform_list_product(
                            raw, channel_uid, store_name, now_iso
                        )
                        if product:
                            all_products.append(product)

                    logger.info(
                        f"[NAVERSTORE] 상품 목록 완료: {store_name} — "
                        f"page={page_num}, {len(raw_products)}개 (누적 {len(all_products)}개)"
                    )

                    if len(all_products) >= total_count:
                        all_products = all_products[:total_count]
                        break

                    if len(raw_products) < page_size:
                        break

        except Exception as e:
            logger.error(f"[NAVERSTORE] 멀티페이지 목록 실패: {store_name} — {e}")

        return {
            "products": all_products,
            "totalCount": total_in_store,
            "fetchedCount": len(all_products),
            "channelUid": channel_uid,
            "storeName": store_name,
        }

    # ------------------------------------------------------------------
    # search() — worker 호환 인터페이스
    # ------------------------------------------------------------------

    async def search(
        self,
        keyword: str,
        max_count: int = 100,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """잡워커 _collect_direct_api 호환 인터페이스.

        keyword = 스마트스토어 URL (전체 또는 카테고리).
        curl_cffi가 SQLAlchemy greenlet과 충돌하므로
        별도 subprocess에서 curl_cffi를 실행하여 완전 격리한다.
        """
        import sys

        store_url = keyword
        store_name = self._extract_store_name(store_url) or ""
        category_id = self._extract_category_id(store_url) or "ALL"
        proxy_url = self._proxy_url or ""

        # 별도 프로세스에서 curl_cffi 실행 — greenlet 충돌 원천 차단
        script = _SUBPROCESS_COLLECT_SCRIPT

        logger.info(
            f"[NAVERSTORE-WORKER] subprocess 수집 시작: {store_name} "
            f"(카테고리={'전체' if category_id == 'ALL' else category_id}, "
            f"목표={max_count}개, 프록시={'Y' if proxy_url else 'N'})"
        )

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            script,
            store_url,
            str(max_count),
            proxy_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        # subprocess stderr 진단 로그 항상 출력
        if stderr:
            for line in stderr.decode(errors="replace").strip().splitlines():
                logger.info(f"[NAVERSTORE-SUB] {line}")

        if proc.returncode != 0:
            logger.error(
                f"[NAVERSTORE-WORKER] subprocess 비정상 종료: code={proc.returncode}"
            )
            return {"products": [], "total": 0}

        try:
            result = json.loads(stdout.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(
                f"[NAVERSTORE-WORKER] JSON 파싱 실패: {e}, "
                f"stdout={stdout.decode(errors='replace')[:200]}"
            )
            return {"products": [], "total": 0}

        products = result.get("products", [])
        total = result.get("total", 0)
        # 상세조회용 채널/스토어 정보 캐시 (worker 가 get_detail 호출 시 재사용)
        _cuid = result.get("channelUid") or ""
        _sname = result.get("storeName") or store_name
        if _cuid:
            self._last_channel_uid = _cuid
        if _sname:
            self._last_store_name = _sname
        logger.info(
            f"[NAVERSTORE-WORKER] subprocess 수집 완료: {store_name} — "
            f"{len(products)}개 (스토어 전체 {total}개, channelUid={_cuid[:10]}...)"
        )
        return {"products": products, "total": total}

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
            or f"{self.BASE_URL}/{store_name}/products/{site_product_id}"
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
    # 상품 상세 조회
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
            product_id = self._extract_product_id(product_url_or_id)
            if not channel_uid:
                channel_uid = await self.resolve_channel_uid(product_url_or_id)
        else:
            product_id = product_url_or_id

        if not product_id:
            logger.error(f"[NAVERSTORE] 상품ID 추출 실패: {product_url_or_id}")
            return {}

        if not channel_uid:
            logger.error(f"[NAVERSTORE] channelUid 없음: {product_url_or_id}")
            return {}

        store_name = self._uid_cache_reverse(channel_uid)
        api_url = (
            f"{self.BASE_URL}/i/v2/channels/{channel_uid}"
            f"/products/{product_id}?withWindow=false"
        )

        logger.info(f"[NAVERSTORE] 상품 상세 조회: {product_id}")

        try:
            from curl_cffi.requests import AsyncSession

            # 쿠키가 있으면 프록시 불필요 (쿠키 자체가 인증 역할)
            proxies = None if cookies else self._build_proxies()
            async with AsyncSession(
                timeout=self._timeout,
                proxies=proxies,
                impersonate="chrome",
            ) as session:
                req_headers = {
                    **self.HEADERS,
                    "Referer": (
                        f"{self.BASE_URL}/{store_name}/products/{product_id}"
                        if store_name
                        else f"{self.BASE_URL}/"
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
            delay = self.DETAIL_DELAY

        results = []
        total = len(product_ids)
        store_name = self._uid_cache_reverse(channel_uid)

        # 쿠키가 있으면 프록시 불필요
        from curl_cffi.requests import AsyncSession

        proxies = None if cookies else self._build_proxies()
        async with AsyncSession(
            timeout=self._timeout,
            proxies=proxies,
            impersonate="chrome",
        ) as session:
            for idx, pid in enumerate(product_ids):
                if idx > 0:
                    await asyncio.sleep(delay)

                api_url = (
                    f"{self.BASE_URL}/i/v2/channels/{channel_uid}"
                    f"/products/{pid}?withWindow=false"
                )

                req_headers = {
                    **self.HEADERS,
                    "Referer": (
                        f"{self.BASE_URL}/{store_name}/products/{pid}"
                        if store_name
                        else f"{self.BASE_URL}/"
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
                            **self.HEADERS,
                            "Referer": f"{self.BASE_URL}/",
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

        # 상품정보고시
        product_notice = data.get("productInfoProvidedNoticeView", {})

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
            "sourceUrl": (f"{self.BASE_URL}/{store_url_path}/products/{product_id}"),
            "collectedAt": now_iso,
            "updatedAt": now_iso,
        }

    # ------------------------------------------------------------------
    # 헬퍼
    # ------------------------------------------------------------------

    def _uid_cache_reverse(self, channel_uid: str) -> str:
        """channelUid로 store_name 역조회."""
        for name, uid in self._uid_cache.items():
            if uid == channel_uid:
                return name
        return ""

    @staticmethod
    def _extract_store_name(url: str) -> Optional[str]:
        """URL에서 스토어명 추출."""
        m = re.search(r"(?:smartstore|brand)\.naver\.com/([a-zA-Z0-9_-]+)", url)
        return m.group(1) if m else None

    @staticmethod
    def _extract_category_id(url: str) -> Optional[str]:
        """URL에서 카테고리 ID 추출. 없으면 None (전체 상품)."""
        m = re.search(r"/category/(\w{8,})", url)
        return m.group(1) if m else None

    @staticmethod
    def _extract_product_id(url: str) -> Optional[str]:
        """URL에서 상품 ID 추출."""
        m = re.search(r"/products/(\d+)", url)
        return m.group(1) if m else None
