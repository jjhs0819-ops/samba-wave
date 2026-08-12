"""플레이오토 EMP 마켓 플러그인.

솔루션 연동형 — 플레이오토 EMP API를 통해 상품 등록/수정/품절.
EMP에 마스터 상품을 등록하면, EMP 스케줄러가 연결된 쇼핑몰에 자동 전송.
"""

import asyncio
import hashlib
import io
import re
from functools import partial
from typing import Any
from urllib.parse import urlparse

import httpx

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.domain.samba.proxy.playauto import PlayAutoClient, PlayAutoApiError
from backend.utils import add_lazy_loading
from backend.utils.logger import logger

# boto3 S3 클라이언트는 인증정보가 동일하면 재사용 — TCP 커넥션 풀 유지로 R2 업로드 오버헤드 감소
_r2_client_cache: dict[str, tuple] = {}

# 이미지 매직 헤더 (JPEG/PNG/GIF/WebP·BMP) — 이 목록에 없으면 이미지가 아니다
_IMAGE_MAGIC_PREFIXES = (b"\xff\xd8", b"\x89PNG", b"GIF8", b"RIFF", b"BM")


def _looks_like_image(head: bytes) -> bool:
    """응답 첫 바이트가 실제 이미지인지 판정.

    소싱처가 원본 이미지를 삭제하면 S3/CDN이 404 에러 XML을 반환하는데,
    이를 검증 없이 넘기면 에러 문서가 .jpg로 위장한 채 EMP까지 전파된다
    (2026-08-12 데상트 391건 — GS이숍 채널등록 '이미지헤더체크:xml' 전량 거절).
    XML/HTML 에러 문서는 '<'로 시작하므로 매직 헤더로만 판정한다.
    """
    if not head:
        return False
    if head.lstrip()[:1] == b"<":  # XML/HTML 에러 문서
        return False
    return any(head.startswith(m) for m in _IMAGE_MAGIC_PREFIXES)


class PlayAutoPlugin(MarketPlugin):
    """플레이오토 EMP 마켓 플러그인."""

    market_type = "playauto"
    policy_key = "플레이오토"
    required_fields = ["name", "sale_price"]

    def _validate_category(self, category_id: str) -> str:
        """플레이오토 카테고리는 8자리 숫자 코드 — 빈 값도 허용."""
        if not category_id:
            return "__SKIP__"
        return category_id

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        """삼바웨이브 상품 → 플레이오토 EMP 포맷 변환."""
        max_stock = int(product.get("_max_stock") or 0)
        options = product.get("options") or []
        real_stock = sum(
            int(o.get("stock") or 0) for o in options if not o.get("isSoldOut")
        )
        if max_stock > 0 and real_stock > 0:
            stock_qty = min(real_stock, max_stock)
        elif max_stock > 0:
            stock_qty = max_stock
        elif real_stock > 0:
            stock_qty = real_stock
        else:
            stock_qty = 99
        return PlayAutoClient.transform_product(
            product=product,
            category_id=category_id if category_id != "__SKIP__" else "",
            stock_qty=stock_qty,
        )

    async def execute(
        self,
        session,
        product: dict,
        creds: dict,
        category_id: str,
        account,
        existing_no: str,
    ) -> dict[str, Any]:
        """플레이오토 EMP API 호출 — 등록 또는 수정."""
        api_key = creds.get("apiKey", "")
        if not api_key:
            return {
                "success": False,
                "message": "플레이오토 API Key가 비어있습니다. 설정에서 API Key를 입력해주세요.",
            }

        # 모든 상품을 고정 카테고리(남성의류>긴팔티셔츠>맨투맨티셔츠)로 전송
        category_id = "11020200"

        # 계정 재고수량 설정 주입 (_max_stock 상한으로 사용)
        extras = (account.additional_fields or {}) if account else {}
        if extras.get("stockQuantity"):
            product = dict(product)
            product["_max_stock"] = int(extras["stockQuantity"])

        # 정책의 플레이오토 전용 설정 주입 (원산지, 시중가비율)
        policy_id = product.get("applied_policy_id")
        if policy_id:
            from backend.domain.samba.policy.repository import SambaPolicyRepository

            policy_repo = SambaPolicyRepository(session)
            policy = await policy_repo.get_async(policy_id)
            if policy and policy.market_policies:
                mp = policy.market_policies.get(self.policy_key, {})
                if mp.get("origin") and not product.get("origin"):
                    product["origin"] = mp["origin"]
                if mp.get("streetPriceRate"):
                    product["_street_price_rate"] = int(mp["streetPriceRate"])

        # 이미지를 R2에 업로드 후 공개 URL로 교체 (소싱처 URL은 외부 접근 불가)
        if not product.get("_skip_image_upload"):
            product = await self._upload_images_to_r2(session, product)
            # [가드] 유효 이미지 0장 — 소싱처가 원본을 전부 삭제한 상태.
            # 그대로 진행하면 이미지 없는 등록/수정으로 상품이 훼손되므로
            # 명시적으로 실패시켜 재수집 후 재전송을 유도한다 (2026-08-12 데상트).
            if product.pop("_all_images_dead", False):
                return {
                    "success": False,
                    "message": (
                        "유효한 상품 이미지가 0장 — 소싱처 원본 소실(404/에러XML). "
                        "이미지 재수집 후 재전송이 필요합니다."
                    ),
                }

        client = PlayAutoClient(api_key)

        try:
            # ── 경량 PATCH 모드 (오토튠 가격/재고만) ─────────────────────
            # _skip_image_upload=True + existing_no → MasterCode + Price + Count + Opts 만 전송.
            # detail_html(65KB)/Images/MyCateName 등 무거운 필드 제외하여 PATCH 0.5초 안에 완료.
            # 2026-05-15 검증: MasterCode + Options만 PATCH 응답 0.4~0.7초.
            if existing_no and product.get("_skip_image_upload"):
                from backend.domain.samba.proxy.playauto import _build_options

                max_stock = int(product.get("_max_stock") or 0)
                options = product.get("options") or []
                real_stock = sum(
                    int(o.get("stock") or 0) for o in options if not o.get("isSoldOut")
                )
                if max_stock > 0 and real_stock > 0:
                    stock_qty = min(real_stock, max_stock)
                elif max_stock > 0:
                    stock_qty = max_stock
                elif real_stock > 0:
                    stock_qty = real_stock
                else:
                    stock_qty = 99

                sale_price = int(product.get("sale_price") or 0)
                minimal: dict[str, Any] = {
                    "MasterCode": existing_no,
                    "Price": str(sale_price),
                    "Count": str(stock_qty),
                }
                if options and isinstance(options, list):
                    emp_opts = _build_options(options, stock_qty)
                    if emp_opts:
                        minimal["Opts"] = emp_opts
                        has_two_axes = any(o.get("title2") for o in emp_opts)
                        minimal["OptSelectType"] = "SM" if has_two_axes else "SS"

                logger.info(
                    f"[플레이오토] 경량 PATCH(가격/재고): MasterCode={existing_no} "
                    f"Price={sale_price} Count={stock_qty} Opts={len(minimal.get('Opts', []))}건"
                )
                # UseNoEditSlave=False → 마스터 Price/Count/Opts를 슬레이브(마켓별 상품)에도 일괄 동기화
                results = await client.update_product(
                    [minimal], use_no_edit_slave=False
                )
            else:
                # 상품 데이터 변환 (전체 payload)
                emp_data = self.transform(product, category_id)

                # 디버그: 실제 전송 데이터 확인
                _img_debug = {
                    f"Image{i}": str(emp_data.get(f"Image{i}", ""))[:80]
                    for i in range(1, 11)
                    if emp_data.get(f"Image{i}")
                }
                logger.info(
                    f"[플레이오토] 전송 데이터: ProdName={emp_data.get('ProdName', '')[:30]}, "
                    f"Price={emp_data.get('Price')}, "
                    f"StreetPrice={emp_data.get('StreetPrice')}, Count={emp_data.get('Count')}, "
                    f"MadeIn={emp_data.get('MadeIn')}, "
                    f"Images={_img_debug}, "
                    f"Opts={len(emp_data.get('Opts', []))}건, "
                    f"Content={len(emp_data.get('Content', ''))}자, "
                    f"MyCateName={emp_data.get('MyCateName', '(미설정)')}"
                )
                logger.info(
                    f"[플레이오토] 원본 images 필드: {[str(u)[:80] for u in (product.get('images') or [])]}"
                )

                if existing_no:
                    emp_data["MasterCode"] = existing_no
                    logger.info(f"[플레이오토] 기존 상품 수정(PATCH): {existing_no}")
                    results = await client.update_product([emp_data])
                else:
                    # 중복등록 원천차단: 같은 ProdName이 이미 EMP에 있으면 등록하지
                    # 않고 기존 MasterCode(동명이면 WriteDate 최신)에 재연결한다.
                    # 타임아웃으로 실패 처리된 상품을 재전송할 때마다 EMP 복제본이
                    # 쌓이던 문제를 등록 '전' 사전확인으로 차단한다.
                    # (타임아웃 자체를 성공으로 보는 금지 패턴과 무관)
                    _prod_name = str(emp_data.get("ProdName", "")).strip()
                    _dup_code = ""
                    try:
                        _dup_code = await client.find_master_code_by_name(_prod_name)
                    except Exception as _pre_e:
                        logger.warning(
                            f"[플레이오토] 중복 사전조회 실패(등록 계속): {_pre_e}"
                        )
                    if _dup_code:
                        logger.warning(
                            f"[플레이오토] 중복등록 방지 — 기등록 재연결: "
                            f"{_prod_name[:30]} → {_dup_code}"
                        )
                        return {
                            "success": True,
                            "product_no": _dup_code,
                            "message": "플레이오토 기등록 재연결 (중복등록 차단)",
                            "data": {"market_product_no": _dup_code},
                        }
                    logger.info("[플레이오토] 신규 등록(POST)")
                    # register 시도 후에는 성공·실패·타임아웃 불문 이름캐시를
                    # 비운다 — EMP에 상품이 만들어졌을 수 있는데 60초 캐시가
                    # 살아 있으면 초 단위 재시도의 사전 중복조회가 그걸 못 보고
                    # 통과해 복제본이 쌓인다(2026-08-06 데상트 189건: 복제 간격
                    # 6초 < TTL 60초). finally라 타임아웃 예외 경로도 덮는다.
                    try:
                        results = await client.register_product([emp_data])
                    finally:
                        client.invalidate_name_master_cache()

            if not results:
                return {
                    "success": False,
                    "message": "플레이오토 API 응답이 비어있습니다.",
                }

            result = results[0] if isinstance(results, list) else results
            status = str(result.get("status", "false")).lower()
            msg = result.get("msg", result.get("message", ""))

            if status == "true":
                master_code = msg if not existing_no else existing_no
                # 신규등록인데 EMP가 성공(status=true)만 주고 MasterCode(msg)를
                # 비워 주는 경우가 있다(실측 56건). 빈 코드로 저장되면 이후 수정/
                # 품절/삭제가 전부 불가 → status=true(EMP가 명시한 확정 성공)일
                # 때만 이름조회로 방금 만든 코드를 회수한다(WriteDate 최신=방금 등록).
                # 타임아웃(응답 없음)에는 이 회수를 하지 않는다(금지 패턴).
                if not existing_no and not str(master_code or "").strip():
                    _prod_name = str(emp_data.get("ProdName", "")).strip()
                    try:
                        master_code = await client.find_master_code_by_name(
                            _prod_name, force_refresh=True
                        )
                    except Exception as _rc_e:
                        logger.error(f"[플레이오토] 마스터코드 회수 조회 실패: {_rc_e}")
                        master_code = ""
                    if master_code:
                        logger.info(
                            f"[플레이오토] 코드 미회신 → 이름조회로 회수: "
                            f"{_prod_name[:30]} → {master_code}"
                        )
                    else:
                        # 회수 실패 → 빈 코드 저장 금지. 실패로 명시해 다음 전송이
                        # 사전조회로 기존 상품에 재연결하도록 한다.
                        logger.error(
                            f"[플레이오토] 등록 성공인데 코드 미회신+회수 실패: "
                            f"{_prod_name[:30]}"
                        )
                        return {
                            "success": False,
                            "message": (
                                "플레이오토 등록됐으나 마스터코드 미회신 — "
                                "재전송 시 사전조회로 재연결됩니다."
                            ),
                            "data": result,
                        }
                logger.info(
                    f"[플레이오토] {'수정' if existing_no else '등록'} 성공: "
                    f"{master_code}"
                )
                return {
                    "success": True,
                    "product_no": master_code,
                    "message": f"플레이오토 {'수정' if existing_no else '등록'} 성공",
                    "data": {
                        "market_product_no": master_code,
                        "raw_response": result,
                    },
                }
            else:
                logger.warning(f"[플레이오토] 실패: {msg}")
                # 플레이오토에서 직접 삭제된 상품 — 재시도/신규등록 차단
                if "마스터상품코드" in msg and "미등록" in msg:
                    return {
                        "success": False,
                        "error_type": "product_not_found",
                        "message": f"플레이오토 실패: {msg}",
                        "_skip_retry": True,
                        "data": result,
                    }
                return {
                    "success": False,
                    "message": f"플레이오토 실패: {msg}",
                    "data": result,
                }

        except PlayAutoApiError as e:
            logger.error(f"[플레이오토] API 에러: {e.message}")
            return {
                "success": False,
                "error_type": "network"
                if "타임아웃" in e.message or "연결" in e.message
                else "unknown",
                "message": e.message,
            }
        finally:
            await client.close()

    @staticmethod
    def _get_proxy_for_download() -> str:
        """이미지 다운로드용 프록시 (Cloud Run에서 소싱처 직접 접근 차단 대응) — DB 설정 페이지 기반."""
        try:
            from backend.domain.samba.collector.refresher import get_collect_proxy_url

            return get_collect_proxy_url() or ""
        except Exception:
            return ""

    async def _upload_images_to_r2(self, session, product: dict) -> dict:
        """소싱처 이미지 → R2 업로드 → 공개 URL로 교체."""
        r2 = await self._get_r2_client(session)
        if not r2:
            logger.warning("[플레이오토] R2 설정 없음 — 이미지 원본 URL 사용")
            return product

        s3_client, bucket_name, public_url, r2_pub_url = r2
        proxy = self._get_proxy_for_download()

        # 상품 1건 처리 중 동일 URL 재업로드 방지 — head_object 호출 횟수 감소
        _url_cache: dict[str, str] = {}

        async def _cached_ensure(dl_client, url: str) -> str:
            if url in _url_cache:
                return _url_cache[url]
            r2_url = await self._ensure_accessible(
                dl_client, s3_client, bucket_name, public_url, url, r2_pub_url
            )
            _url_cache[url] = r2_url
            return r2_url

        # 대표/추가 이미지 R2 업로드
        images = product.get("images") or []
        if images:
            async with httpx.AsyncClient(
                timeout=30, follow_redirects=True, proxy=proxy if proxy else None
            ) as dl_client:
                # [가드] 최종 URL 생존 검증 캐시 (동일 URL 중복 프로브 방지)
                _alive_cache: dict[str, bool] = {}

                async def _upload_one(img_entry):
                    url = (
                        img_entry
                        if isinstance(img_entry, str)
                        else img_entry.get("url", "")
                    )
                    if not url:
                        return None
                    try:
                        final = await _cached_ensure(dl_client, url)
                    except Exception as e:
                        logger.warning(f"[플레이오토] 이미지 처리 실패: {e}")
                        final = url
                    # [가드] EMP에 넘기기 전에 최종 URL이 실제 이미지인지 검증.
                    # 무신사 등 화이트리스트 밖 도메인은 원본 URL을 그대로 넘기는데,
                    # 소싱처가 원본을 삭제했으면 404 에러 XML이 .jpg로 위장한 채
                    # EMP에 저장된다 (2026-08-12 데상트 391건 — EMP 등록은 통과하고
                    # GS이숍 채널등록의 이미지 헤더 체크에서 전량 거절). 죽은 이미지는
                    # 여기서 걸러 EMP 전파를 차단한다.
                    if final not in _alive_cache:
                        _alive_cache[final] = await self._probe_image_alive(
                            dl_client, final
                        )
                    if not _alive_cache[final]:
                        logger.warning(
                            f"[플레이오토] 죽은 이미지 제외(원본 소실/에러문서): "
                            f"{str(final)[:100]}"
                        )
                        return None
                    return final

                results = await asyncio.gather(
                    *[_upload_one(img) for img in images[:10]]
                )
            valid_images = [r for r in results if r]
            if not valid_images:
                # 전 이미지 소실 — 이미지 없는 등록/수정은 상품 훼손이므로 명시적 실패
                product["images"] = []
                product["_all_images_dead"] = True
            else:
                product["images"] = valid_images

        # detail_html 보강: detail_images 리스트가 detail_html의 <img>보다 많으면 재구성.
        # ABC마트/롯데ON 등 lazy-load 사이트는 detail_html에 placeholder src 1개만 들어있어
        # Content가 183자 등 매우 짧게 저장되는 경우가 있다. 이때 detail_images 리스트(파서가
        # data-src까지 모두 추출)를 기반으로 HTML을 재구성해 모든 이미지가 EMP에 표시되도록 보장.
        detail_html = product.get("detail_html", "") or ""
        detail_imgs = product.get("detail_images") or []
        if isinstance(detail_imgs, list) and detail_imgs:
            existing_srcs = re.findall(
                r'<img[^>]+src=["\']([^"\']+)["\']', detail_html, re.IGNORECASE
            )
            if len(existing_srcs) < len(detail_imgs):
                logger.info(
                    f"[플레이오토] detail_html 재구성: 기존 src={len(existing_srcs)}개 < "
                    f"detail_images={len(detail_imgs)}개 → 이미지 리스트 기반 재생성"
                )
                rebuilt_parts = []
                for u in detail_imgs:
                    url_str = (
                        u
                        if isinstance(u, str)
                        else (u.get("url", "") if isinstance(u, dict) else "")
                    )
                    if not url_str:
                        continue
                    if url_str.startswith("//"):
                        url_str = f"https:{url_str}"
                    rebuilt_parts.append(
                        f'<p style="text-align:center"><img src="{url_str}" /></p>'
                    )
                if rebuilt_parts:
                    detail_html = "\n".join(rebuilt_parts)

        # 상세설명 HTML 내 이미지도 동일 처리 + lazy loading 삽입 (메인 이미지 캐시 공유)
        if detail_html:
            replaced = await self._replace_detail_images(
                detail_html,
                s3_client,
                bucket_name,
                public_url,
                proxy,
                url_cache=_url_cache,
            )
            product["detail_html"] = add_lazy_loading(replaced)

        return product

    # PlayAuto EMP 서버가 직접 가져갈 수 없어 R2 미러가 필요한 도메인 화이트리스트.
    # 실측(2026-05-15) 기준: GSShop(asset.m-gs.kr 등) / FashionPlus 미러링 시 PlayAuto가
    # 응답 못 주고 90초+ 행업 → R2 업로드 필요.
    # MUSINSA(msscdn) / ABCmart(a-rt.com) / LOTTEON(contents.lotteon.com) / SSG는
    # 직접 URL로 1~16초만에 등록 성공 — R2 우회 불필요.
    _R2_REQUIRED_HOSTS = (
        "asset.m-gs.kr",
        "static.m-gs.kr",
        "gsshop.com",
        "fashionplus.co.kr",
        "img.fashionplus.co.kr",
    )

    async def _ensure_accessible(
        self,
        dl_client: httpx.AsyncClient,
        s3_client,
        bucket_name: str,
        public_url: str,
        image_url: str,
        r2_pub_url: str = "",
    ) -> str:
        """소싱처 이미지 → 필요한 경우에만 R2 업로드 후 pub URL 반환.

        - 이미 우리 도메인(/images/playauto/v5/) → r2.dev clean URL로 교체
        - 화이트리스트 도메인(GSShop/FashionPlus) → R2 업로드 → r2.dev clean URL
        - 그 외(무신사/ABCmart/롯데ON 등) → 원본 URL 그대로 (PlayAuto 직접 fetch 가능)

        r2_pub_url: pub-xxx.r2.dev 형식 (PlayAuto 서버 접근 가능한 clean URL).
        없으면 public_url(Caddy 경유) 사용(2026-06-18 실측: Caddy 경유 504).
        """
        host = (urlparse(image_url).netloc or "").lower()

        def _clean_url(r2_key: str) -> str:
            """r2_pub_url이 있으면 r2.dev clean URL, 없으면 Caddy URL."""
            if r2_pub_url:
                return f"{r2_pub_url}/{r2_key}"
            return f"{public_url}/{r2_key}"

        # 이미 우리 도메인 — R2 key 추출 후 r2.dev URL로 교체
        # (PlayAuto 서버에서 api.samba-wave.co.kr 직접 도달 불가 → 504)
        if "samba-wave.co.kr" in host:
            path = urlparse(image_url).path
            if "/images/" in path:
                r2_key = path.split("/images/", 1)[1]
                return _clean_url(r2_key)
            return image_url

        # 화이트리스트에 없으면 원본 URL 그대로 (PlayAuto가 직접 fetch 가능)
        if not any(blocked in host for blocked in self._R2_REQUIRED_HOSTS):
            return image_url

        # 차단 도메인 — R2 업로드 필요
        # 해시 기반 중복 방지 — 동일 소싱처 URL은 같은 R2 파일로
        url_hash = hashlib.md5(image_url.encode()).hexdigest()[:12]
        ext = ".jpg"
        low = image_url.lower()
        if low.endswith(".png"):
            ext = ".png"
        elif low.endswith(".gif"):
            ext = ".gif"
        r2_key = f"playauto/v5/{url_hash}{ext}"

        # R2에 이미 존재하면 재업로드 스킵
        try:
            await asyncio.to_thread(
                partial(s3_client.head_object, Bucket=bucket_name, Key=r2_key)
            )
            return _clean_url(r2_key)
        except Exception:
            pass

        return await self._upload_single_image(
            dl_client, s3_client, bucket_name, public_url, image_url, r2_key, r2_pub_url
        )

    @staticmethod
    def _download_headers(image_url: str) -> dict[str, str]:
        """이미지 다운로드용 헤더 (소싱처별 Referer 설정)."""
        parsed = urlparse(image_url)
        referer = f"{parsed.scheme}://{parsed.netloc}/"
        if "msscdn.net" in (parsed.netloc or "") or "musinsa" in (parsed.netloc or ""):
            referer = "https://www.musinsa.com/"
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": referer,
            "Accept": "image/jpeg,image/png,image/gif,*/*",
        }

    async def _probe_image_alive(
        self, dl_client: httpx.AsyncClient, image_url: str
    ) -> bool:
        """URL이 실제 이미지를 서빙하는지 경량 검증 (Range 32바이트 + 매직 헤더).

        소싱처가 원본을 삭제하면 404 또는 '200인데 본문은 에러 XML'이 온다 —
        상태코드만으로는 못 거르므로 첫 바이트의 매직 헤더로 판정한다.
        일시 네트워크 오류로 정상 이미지를 죽었다고 오판하지 않도록 1회 재시도.
        """
        if not str(image_url).lower().startswith(("http://", "https://")):
            return True  # 프로브 불가 스킴은 기존 동작 유지
        headers = {**self._download_headers(image_url), "Range": "bytes=0-31"}
        for attempt in range(2):
            try:
                resp = await dl_client.get(image_url, headers=headers)
                if resp.status_code in (200, 206):
                    return _looks_like_image(resp.content[:32])
                if resp.status_code in (404, 410):
                    return False
                # 403/5xx 등 애매한 상태 — 재시도 후에도 애매하면 살아있다고 간주
                # (Range 미지원·핫링크 차단 등 서버 특성일 수 있어 오차단 방지)
            except Exception:
                pass
            await asyncio.sleep(0.5)
        return True

    async def _upload_single_image(
        self,
        dl_client: httpx.AsyncClient,
        s3_client,
        bucket_name: str,
        public_url: str,
        image_url: str,
        r2_key: str = "",
        r2_pub_url: str = "",
    ) -> str:
        """이미지 1장 다운로드 → R2 업로드 → 공개 URL 반환."""

        headers = self._download_headers(image_url)
        resp = await dl_client.get(image_url, headers=headers)
        resp.raise_for_status()
        image_bytes = resp.content
        if len(image_bytes) < 1000:
            raise ValueError(f"이미지 비정상 크기: {len(image_bytes)}B")

        # 포맷 감지 — JPEG/PNG/GIF가 아니면 Pillow로 JPG 변환
        is_jpeg = image_bytes[:2] == b"\xff\xd8"
        is_png = image_bytes[:4] == b"\x89PNG"
        is_gif = image_bytes[:4] == b"GIF8"
        logger.info(
            f"[플레이오토] 이미지 다운로드: {image_url[:80]}, "
            f"size={len(image_bytes)}B, magic={image_bytes[:4].hex()}"
        )
        if not (is_jpeg or is_png or is_gif):
            from PIL import Image as _PILImage

            _img = _PILImage.open(io.BytesIO(image_bytes))
            if _img.mode in ("RGBA", "P"):
                _img = _img.convert("RGB")
            _buf = io.BytesIO()
            _img.save(_buf, format="JPEG", quality=90)
            image_bytes = _buf.getvalue()
            logger.info(f"[플레이오토] 비표준→JPG 변환: {image_url[:60]}")

        # R2 키 (해시 기반 중복 방지)
        if not r2_key:
            url_hash = hashlib.md5(image_url.encode()).hexdigest()[:12]
            ext = ".jpg"
            if image_url.lower().endswith(".png"):
                ext = ".png"
            elif image_url.lower().endswith(".gif"):
                ext = ".gif"
            r2_key = f"playauto/v5/{url_hash}{ext}"

        content_type = "image/jpeg"
        if r2_key.endswith(".png"):
            content_type = "image/png"
        elif r2_key.endswith(".gif"):
            content_type = "image/gif"

        await asyncio.to_thread(
            partial(
                s3_client.upload_fileobj,
                io.BytesIO(image_bytes),
                bucket_name,
                r2_key,
                ExtraArgs={"ContentType": content_type},
            )
        )

        if r2_pub_url:
            return f"{r2_pub_url}/{r2_key}"
        return f"{public_url}/{r2_key}"

    async def _replace_detail_images(
        self,
        html: str,
        s3_client,
        bucket_name: str,
        public_url: str,
        proxy: str = "",
        url_cache: dict | None = None,
    ) -> str:
        """상세설명 HTML 내 외부 이미지 URL을 R2 URL로 교체.

        ABC마트/롯데ON 등은 lazy-load 패턴(`<img src="placeholder.gif" data-src="진짜.jpg">`)
        을 사용. EMP는 src 속성만 인식하므로:
        1) data-src/data-lazy/data-original 값을 src로 승격 (placeholder 제거)
        2) src + data-* 속성에 들어있는 모든 외부 URL을 R2로 업로드 후 치환
        """

        # 1) lazy-load 속성을 src로 승격 — img 태그 단위로 처리
        def _promote_lazy(m: re.Match) -> str:
            tag = m.group(0)
            lazy_match = re.search(
                r'(?:data-src|data-lazy|data-lazy-src|data-original)=["\']([^"\']+)["\']',
                tag,
                re.IGNORECASE,
            )
            if not lazy_match:
                return tag
            real_url = lazy_match.group(1)
            if not real_url:
                return tag
            # 기존 src=... 가 있으면 진짜 URL로 교체, 없으면 추가
            if re.search(r"\ssrc=", tag, re.IGNORECASE):
                tag = re.sub(
                    r'(\ssrc=)(["\'])[^"\']*\2',
                    lambda mm: f"{mm.group(1)}{mm.group(2)}{real_url}{mm.group(2)}",
                    tag,
                    count=1,
                    flags=re.IGNORECASE,
                )
            else:
                tag = tag.replace("<img", f'<img src="{real_url}"', 1)
            return tag

        html = re.sub(r"<img\b[^>]*>", _promote_lazy, html, flags=re.IGNORECASE)

        # 2) src + 잔여 data-* 속성 모두에서 외부 URL 추출
        img_pattern = re.compile(
            r'(?:src|data-src|data-lazy|data-lazy-src|data-original)=["\']([^"\']+)["\']',
            re.IGNORECASE,
        )
        urls = img_pattern.findall(html)

        if not urls:
            return html

        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True, proxy=proxy if proxy else None
        ) as dl_client:

            async def _replace_one(url):
                if not url or url.startswith("data:"):
                    return url, url
                if public_url and public_url in url:
                    return url, url
                try:
                    if url_cache is not None and url in url_cache:
                        return url, url_cache[url]
                    r2_url = await self._ensure_accessible(
                        dl_client, s3_client, bucket_name, public_url, url
                    )
                    if url_cache is not None:
                        url_cache[url] = r2_url
                    return url, r2_url
                except Exception as e:
                    logger.warning(f"[플레이오토] 상세 이미지 R2 업로드 실패: {e}")
                    return url, url

            replacements = await asyncio.gather(*[_replace_one(u) for u in urls])

        for orig_url, r2_url in replacements:
            if orig_url != r2_url:
                html = html.replace(orig_url, r2_url)

        return html

    async def _get_r2_client(self, session):
        """R2 클라이언트 가져오기 (인증정보 동일 시 캐시 재사용)."""
        from backend.domain.samba.forbidden.model import SambaSettings
        from sqlmodel import select

        stmt = select(SambaSettings).where(SambaSettings.key == "cloudflare_r2")
        result = await session.execute(stmt)
        row = result.scalars().first()
        creds = row.value if (row and isinstance(row.value, dict)) else None
        try:
            await session.commit()
        except Exception:
            pass
        if not creds:
            return None
        account_id = str(creds.get("accountId", "")).strip()
        access_key = str(creds.get("accessKey", "")).strip()
        secret_key = str(creds.get("secretKey", "")).strip()
        bucket_name = str(creds.get("bucketName", "")).strip()
        r2_public_url = str(creds.get("publicUrl", "")).strip().rstrip("/")
        # PlayAuto 이미지 전용 public URL (r2.dev direct).
        # PlayAuto 서버가 api.samba-wave.co.kr(Caddy 경유)에 접근 불가 → 504.
        # r2PubUrl(r2.dev)로 직접 서빙하면 1.4초 내 등록 성공(2026-06-18 실측).
        r2_pub_url = str(creds.get("r2PubUrl", "")).strip().rstrip("/")

        if not access_key or not secret_key or not bucket_name:
            return None

        cache_key = hashlib.md5(
            f"{account_id}:{access_key}:{secret_key}:{bucket_name}".encode()
        ).hexdigest()
        if cache_key in _r2_client_cache:
            return _r2_client_cache[cache_key]

        try:
            import boto3

            client = boto3.client(
                "s3",
                endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name="auto",
            )
            _r2_client_cache[cache_key] = (
                client,
                bucket_name,
                r2_public_url,
                r2_pub_url,
            )
            return _r2_client_cache[cache_key]
        except Exception:
            return None

    async def delete(self, session, product_no: str, account) -> dict[str, Any]:
        """상품 품절 처리: 재고 0 → 취소대기 순으로 처리 (EMP 상품 등록 전 상태 대응)."""
        creds = await self._load_auth(session, account)
        if not creds:
            return {"success": False, "message": "플레이오토 인증정보 없음"}

        api_key = creds.get("apiKey", "")
        if not api_key:
            return {"success": False, "message": "플레이오토 API Key가 비어있습니다."}

        client = PlayAutoClient(api_key)
        try:
            # 1단계: 재고 0으로 설정 (마켓 등록 전 상품은 soldout 불가이므로 선행 필요)
            #
            # EMP PATCH /prods 는 Price 와 Count 를 항상 함께 요구한다. Count 만 보내면
            # EMP 가 요청을 거부해 재고가 내려가지 않고, 삼바에서 삭제된 뒤에도 마켓에
            # 재고가 살아있는 "유령"이 발생한다(2026-07 대량 유령 정리의 근본 원인).
            # → 현재 상품을 조회해 Price(및 옵션)를 확보한 뒤 Price+Count(+Opts) 로 전송.
            try:
                zero_payload: dict[str, Any] = {"MasterCode": product_no, "Count": "0"}
                try:
                    detail = await client.get_product(product_no)
                    if isinstance(detail, dict):
                        zero_payload["Price"] = str(detail.get("Price") or "0")
                        opts = detail.get("Opts")
                        if isinstance(opts, list) and opts:
                            zeroed_opts = []
                            for opt in opts:
                                if isinstance(opt, dict):
                                    zo = dict(opt)
                                    zo["stock"] = "0"
                                    zo["soldout"] = "1"
                                    zeroed_opts.append(zo)
                            if zeroed_opts:
                                zero_payload["Opts"] = zeroed_opts
                                if detail.get("OptSelectType"):
                                    zero_payload["OptSelectType"] = detail[
                                        "OptSelectType"
                                    ]
                except Exception as lookup_err:
                    logger.warning(
                        f"[플레이오토] 재고0 전 상품조회 실패(Price=0으로 진행): "
                        f"{product_no} - {lookup_err}"
                    )
                    zero_payload.setdefault("Price", "0")
                # UseNoEditSlave 기본(False) → 슬레이브(마켓별 상품)에도 재고0 전파
                await client.update_product([zero_payload])
                logger.info(f"[플레이오토] 재고 0 처리 완료: {product_no}")
            except Exception as e:
                logger.warning(
                    f"[플레이오토] 재고 0 처리 실패 (soldout 계속 진행): {product_no} - {e}"
                )

            # 2단계: 취소대기 전환
            results = await client.soldout_product([product_no])
            if not results:
                # 빈 응답 = EMP 가 요청을 무시한 것(본문 형식 오류 등). 상품 상태
                # 문제로 단정하면 안 된다 — 2026-07-28 실측에서 CSV 문자열 본문이
                # 조용히 [] 만 반환했고, 그 탓에 판매중지가 내내 실패하고 있었다.
                return {
                    "success": False,
                    "message": "플레이오토 품절 실패: EMP 빈 응답(요청 미반영) — 요청 형식/상품 상태 확인 필요",
                }
            result = results[0] if isinstance(results, list) else results
            status = str(result.get("status", "false")).lower()
            # EMP 응답 키는 message — msg 만 보면 실패 사유가 늘 빈 문자열이 된다
            msg = result.get("message") or result.get("msg") or ""

            if status == "true":
                logger.info(f"[플레이오토] 취소대기 전환 성공: {product_no}")
                return {"success": True, "message": f"플레이오토 품절 처리 완료: {msg}"}
            else:
                return {"success": False, "message": f"플레이오토 품절 실패: {msg}"}
        except PlayAutoApiError as e:
            return {"success": False, "message": e.message}
        finally:
            await client.close()

    async def test_auth(self, session, account) -> bool:
        """API 키 인증 테스트."""
        creds = await self._load_auth(session, account)
        if not creds:
            return False

        api_key = creds.get("apiKey", "")
        if not api_key:
            return False

        client = PlayAutoClient(api_key)
        try:
            return await client.test_connection()
        finally:
            await client.close()
