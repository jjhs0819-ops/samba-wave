"""플레이오토 EMP API 클라이언트."""

from typing import Any

import httpx

from backend.utils.logger import logger

# EMP API 기본 URL
EMP_BASE_URL = "https://playauto-api.playauto.co.kr/emp/v1"
# 공통 API 기본 URL
COMMON_BASE_URL = "https://playapi.api.plto.com/restApi/empapi"


class PlayAutoApiError(Exception):
    """플레이오토 API 에러."""

    def __init__(self, message: str, status: int = 0, data: Any = None):
        self.message = message
        self.status = status
        self.data = data
        super().__init__(message)


class PlayAutoClient:
    """플레이오토 EMP API 클라이언트.

    인증: X-API-KEY 헤더
    상품 등록/수정/품절, 주문 조회, 송장 입력, 문의 조회/답변
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            # Cloud Run → PlayAuto 직접 연결 차단 시 프록시 사용
            proxy = self._get_proxy_url()
            if proxy:
                logger.info(
                    f"[플레이오토] 프록시 사용: {proxy.split('@')[-1] if '@' in proxy else 'on'}"
                )
            else:
                logger.warning("[플레이오토] 프록시 미설정 — 직접 연결")
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=15.0),
                follow_redirects=True,
                proxy=proxy if proxy else None,
            )
        return self._client

    @staticmethod
    def _get_proxy_url() -> str:
        """수집용 프록시 URL 가져오기."""
        try:
            from backend.core.config import settings

            url = settings.collect_proxy_url or ""
            return url.strip()
        except Exception as e:
            logger.warning(f"[플레이오토] 프록시 설정 로드 실패: {e}")
            return ""

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> dict[str, str]:
        return {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }

    async def _call_api(
        self,
        method: str,
        url: str,
        body: dict | list | None = None,
        params: dict | None = None,
    ) -> Any:
        """API 호출 공통 메서드."""
        client = self._get_client()
        headers = self._headers()

        kwargs: dict[str, Any] = {"headers": headers}
        if body is not None:
            kwargs["json"] = body
        if params is not None:
            kwargs["params"] = params

        try:
            resp = await client.request(method, url, **kwargs)
        except httpx.TimeoutException as e:
            raise PlayAutoApiError(f"[플레이오토] 타임아웃: {e}") from e
        except httpx.ConnectError as e:
            raise PlayAutoApiError(f"[플레이오토] 연결 실패: {e}") from e

        # 응답 파싱
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}

        # HTTP 에러 체크
        if resp.status_code >= 500:
            msg = ""
            if isinstance(data, dict):
                msg = data.get("message", data.get("msg", str(data)))
            raise PlayAutoApiError(
                f"[플레이오토] 서버 에러({resp.status_code}): {msg}",
                status=resp.status_code,
                data=data,
            )

        return data

    # ── 상품 API ──

    async def register_product(self, products: list[dict]) -> list[dict]:
        """상품 일괄 등록 (POST /prods).

        Args:
            products: 상품 데이터 리스트 (transform_product 결과)

        Returns:
            [{code, status, msg}, ...]
        """
        url = f"{EMP_BASE_URL}/prods"
        body = {"data": products}
        result = await self._call_api("POST", url, body=body)
        logger.info(f"[플레이오토] 상품 등록 응답: {result}")
        return result if isinstance(result, list) else [result]

    async def update_product(
        self, products: list[dict], use_no_edit_slave: bool = False
    ) -> list[dict]:
        """상품 일괄 수정 (PATCH /prods).

        Args:
            products: 수정할 상품 데이터 리스트 (MasterCode 필수)
            use_no_edit_slave: True면 슬레이브 정보 수정 안 함

        Returns:
            [{code, status, msg}, ...]
        """
        url = f"{EMP_BASE_URL}/prods"
        body: dict[str, Any] = {"data": products}
        if use_no_edit_slave:
            body["UseNoEditSlave"] = True
        result = await self._call_api("PATCH", url, body=body)
        logger.info(f"[플레이오토] 상품 수정 응답: {result}")
        return result if isinstance(result, list) else [result]

    async def soldout_product(self, master_codes: list[str]) -> list[dict]:
        """상품 품절 처리 (PATCH /prods/soldout).

        '판매중', '수정대기', '종료대기' → '취소대기'로 변경.
        """
        url = f"{EMP_BASE_URL}/prods/soldout"
        body = {"data": ",".join(master_codes)}
        result = await self._call_api("PATCH", url, body=body)
        logger.info(f"[플레이오토] 상품 품절 응답: {result}")
        return result if isinstance(result, list) else [result]

    async def get_product(self, master_code: str) -> dict:
        """상품 한건 조회 (GET /prods)."""
        url = f"{EMP_BASE_URL}/prods"
        return await self._call_api("GET", url, params={"MasterCode": master_code})

    async def get_products(self) -> list[dict]:
        """상품 다중 조회 (GET /prods/info/lookupProd)."""
        url = f"{EMP_BASE_URL}/prods/info/lookupProd"
        result = await self._call_api("GET", url)
        return result if isinstance(result, list) else [result]

    # ── 주문 API ──

    async def get_orders(
        self,
        malls: list[str] | None = None,
        states: str = "",
        start_date: str = "",
        end_date: str = "",
        page: int = 1,
        count: int = 100,
        master_code: str = "",
        tel: str = "",
        customer: str = "",
    ) -> list[dict]:
        """주문 일괄 조회 (GET /orders)."""
        url = f"{EMP_BASE_URL}/orders"
        params: dict[str, Any] = {"page": page, "count": count}
        if malls:
            for i, mall in enumerate(malls):
                params[f"malls[{i}]"] = mall
        if states:
            params["states"] = states
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
        if master_code:
            params["MasterCode"] = master_code
        if tel:
            params["tel"] = tel
        if customer:
            params["customer"] = customer

        result = await self._call_api("GET", url, params=params)
        return result if isinstance(result, list) else [result]

    async def get_order(self, number: int) -> dict:
        """주문 한건 조회 (GET /orders/{number})."""
        url = f"{EMP_BASE_URL}/orders"
        return await self._call_api("GET", url, params={"number": number})

    async def get_order_count(
        self,
        malls: list[str] | None = None,
        states: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> int:
        """주문 총 수량 조회."""
        url = f"{EMP_BASE_URL}/orders/count"
        params: dict[str, Any] = {}
        if malls:
            for i, mall in enumerate(malls):
                params[f"malls[{i}]"] = mall
        if states:
            params["states"] = states
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date

        result = await self._call_api("GET", url, params=params)
        if isinstance(result, dict):
            return int(result.get("count", 0))
        return 0

    async def get_order_cs(self, number: int) -> list[dict]:
        """주문 CS 로그 조회."""
        url = f"{EMP_BASE_URL}/orders/cs"
        result = await self._call_api("GET", url, params={"number": number})
        return result if isinstance(result, list) else [result]

    # ── 송장 API ──

    async def send_invoice(
        self,
        invoices: list[dict],
        change_state: bool = True,
        overwrite: bool = True,
    ) -> list[dict]:
        """송장 입력 (PATCH /senders).

        Args:
            invoices: [{number, sender(택배사코드), senderno(송장번호)}, ...]
            change_state: True=출고로 변경, False=송장입력으로 변경
            overwrite: True=기존 송장 덮어쓰기
        """
        url = f"{EMP_BASE_URL}/senders"
        body = {
            "changeState": change_state,
            "overWrite": overwrite,
            "data": invoices,
        }
        result = await self._call_api("PATCH", url, body=body)
        logger.info(f"[플레이오토] 송장 입력 응답: {result}")
        return result if isinstance(result, list) else [result]

    # ── 문의 API ──

    async def get_qnas(
        self,
        malls: list[str] | None = None,
        states: str = "",
        start_date: str = "",
        end_date: str = "",
        page: int = 1,
        count: int = 100,
    ) -> list[dict]:
        """문의 일괄 조회 (GET /qnas)."""
        url = f"{EMP_BASE_URL}/qnas"
        params: dict[str, Any] = {"page": page, "count": count}
        if malls:
            for i, mall in enumerate(malls):
                params[f"malls[{i}]"] = mall
        if states:
            params["states"] = states
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date

        result = await self._call_api("GET", url, params=params)
        if isinstance(result, dict) and "rows" in result:
            rows = result["rows"]
            return rows if isinstance(rows, list) else [rows]
        return result if isinstance(result, list) else [result]

    async def answer_qna(
        self, answers: list[dict], overwrite: bool = False
    ) -> list[dict]:
        """문의 답변 등록 (PATCH /qnas).

        Args:
            answers: [{number, Asubject, AContent}, ...]
            overwrite: 답변 덮어쓰기 여부
        """
        url = f"{EMP_BASE_URL}/qnas"
        body = {"overWrite": overwrite, "data": answers}
        result = await self._call_api("PATCH", url, body=body)
        logger.info(f"[플레이오토] 문의 답변 응답: {result}")
        if isinstance(result, dict) and "rows" in result:
            rows = result["rows"]
            return rows if isinstance(rows, list) else [rows]
        return result if isinstance(result, list) else [result]

    # ── 공통 API ──

    async def get_market_list(self) -> list[dict]:
        """쇼핑몰 정보 조회 (GET /getMarketList)."""
        url = f"{COMMON_BASE_URL}/getMarketList"
        result = await self._call_api("GET", url)
        if isinstance(result, dict) and result.get("success") == "true":
            rows = result.get("rows", [])
            return rows if isinstance(rows, list) else [rows]
        return []

    async def get_deliv_codes(self) -> list[dict]:
        """택배사 코드 조회 (GET /getDelivCode)."""
        url = f"{COMMON_BASE_URL}/getDelivCode"
        result = await self._call_api("GET", url)
        if isinstance(result, dict) and result.get("success") == "true":
            rows = result.get("rows", [])
            return rows if isinstance(rows, list) else [rows]
        return []

    async def get_match_categories(self) -> list[dict]:
        """표준 카테고리 조회 (GET /getMatchCate)."""
        url = f"{COMMON_BASE_URL}/getMatchCate"
        result = await self._call_api("GET", url)
        if isinstance(result, dict) and result.get("success") == "true":
            rows = result.get("rows", [])
            return rows if isinstance(rows, list) else [rows]
        return []

    async def get_mall_sites(self) -> list[dict]:
        """사용중인 쇼핑몰 조회 (GET /get-mall-site)."""
        url = f"{EMP_BASE_URL}/members/get-mall-site"
        result = await self._call_api("GET", url)
        return result if isinstance(result, list) else [result]

    # ── 인증 테스트 ──

    async def test_connection(self) -> bool:
        """API 키 유효성 확인 — 상품 다중 조회로 테스트."""
        try:
            await self.get_products()
            return True
        except PlayAutoApiError:
            return False
        except Exception:
            return False

    # ── 상품 데이터 변환 ──

    @staticmethod
    def transform_product(
        product: dict,
        category_id: str = "",
        stock_qty: int = 999,
        deliv_method: str = "선결제",
        deliv_price: str = "0",
    ) -> dict[str, Any]:
        """삼바웨이브 상품 → 플레이오토 EMP API 포맷 변환.

        Args:
            product: 삼바웨이브 수집 상품 dict
            category_id: 플레이오토 카테고리 코드
            stock_qty: 기본 재고수량
            deliv_method: 배송방법 (착불/무료/선결제)
            deliv_price: 배송비

        Returns:
            EMP 상품등록 API에 맞는 dict
        """
        # 기본 정보
        data: dict[str, Any] = {
            "MasterCode": "__AUTO__",
            "ProdName": str(product.get("name", ""))[:200],
            "Price": str(int(product.get("sale_price", 0))),
            "Count": str(stock_qty),
            "MadeIn": _normalize_origin(product.get("origin")),
            "TaxType": "Y",
        }

        # 원가 (소싱처 원가 = cost 필드)
        cost = (
            product.get("cost")
            or product.get("cost_price")
            or product.get("source_price")
        )
        if cost:
            data["CostPrice"] = str(int(cost))

        # 시중가: 정책의 streetPriceRate(%) 적용, 0이면 판매가와 동일
        sale_price = int(product.get("sale_price", 0))
        street_rate = product.get("_street_price_rate", 0)
        if street_rate and sale_price:
            data["StreetPrice"] = str(int(sale_price * (1 + street_rate / 100)))
        else:
            data["StreetPrice"] = str(sale_price)

        # 카테고리
        if category_id:
            data["CateCode"] = str(category_id)

        # 브랜드/제조사/모델명
        brand = product.get("brand", "")
        if brand:
            data["Brand"] = str(brand)
        maker = product.get("maker", "") or product.get("manufacturer", "")
        if maker:
            data["Maker"] = str(maker)
        # 모델명 = 품번 (site_product_id 또는 product_code)
        model = (
            product.get("product_code")
            or product.get("site_product_id")
            or product.get("sku_code")
            or ""
        )
        if model:
            data["Model"] = str(model)

        # 이미지 (최대 10개, 빈 항목 건너뛰고 순차 배치)
        # EMP는 JPG/JPEG/PNG/GIF/BMP 확장자만 허용
        images = product.get("images") or []
        img_idx = 1
        if isinstance(images, list):
            for img_url in images:
                if img_idx > 10:
                    break
                url = img_url if isinstance(img_url, str) else img_url.get("url", "")
                if not url:
                    continue
                # 프로토콜 보정
                if url.startswith("//"):
                    url = f"https:{url}"
                # 확장자 없는 URL에 .jpg 추가 (R2/CDN URL 대응)
                if not any(
                    url.lower().endswith(ext)
                    for ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")
                ):
                    url = url + ".jpg"
                # WebP → JPG 변환 (EMP 미지원)
                if url.lower().endswith(".webp"):
                    url = url[:-5] + ".jpg"
                data[f"Image{img_idx}"] = url
                img_idx += 1

        # 상세설명 HTML
        content = product.get("detail_html", "") or product.get("description", "")
        if content:
            data["Content"] = str(content)

        # 배송 정보
        data["DelivMethod"] = deliv_method
        data["DelivPrice"] = str(deliv_price)

        # 정책에서 주입된 배송비 적용
        if product.get("_delivery_fee_type") == "PAID":
            base_fee = product.get("_delivery_base_fee", 0)
            data["DelivMethod"] = "선결제"
            data["DelivPrice"] = str(base_fee)
        elif product.get("_delivery_fee_type") == "FREE":
            data["DelivMethod"] = "무료"
            data["DelivPrice"] = "0"

        # 재고수량 정책 반영
        max_stock = product.get("_max_stock")
        if max_stock:
            stock_qty = int(max_stock)
            data["Count"] = str(stock_qty)

        # 키워드 (태그에서 최대 5개)
        tags = product.get("tags") or []
        if isinstance(tags, list):
            for i, tag in enumerate(tags[:5], 1):
                tag_str = str(tag).strip() if tag else ""
                if tag_str:
                    data[f"Keyword{i}"] = tag_str

        # 옵션 변환
        options = product.get("options") or []
        if options and isinstance(options, list):
            emp_opts = _build_options(options, stock_qty)
            if emp_opts:
                data["Opts"] = emp_opts
                # 옵션 타입 결정 (옵션축 개수에 따라)
                has_two_axes = any(o.get("title2") for o in emp_opts)
                data["OptSelectType"] = "SM" if has_two_axes else "SS"

        # 품목정보고시 — 상품 데이터로 채우기 (code=35: 기타재화)
        as_phone = product.get("_as_phone", "")
        # 품목정보의 원산지는 국가명만 (예: "중국", 비어있으면 "상세설명참조")
        raw_origin = product.get("origin") or ""
        siil_origin = (
            raw_origin.strip()
            if raw_origin.strip() not in ("기타", "국내", "")
            else "[상세설명참조]"
        )
        maker = data.get("Maker", "")
        data["SiilData"] = [
            {
                "code": "35",
                "data1": str(product.get("name", ""))[:100] or "[상세설명참조]",
                "data2": data.get("Model", "[상세설명참조]"),
                "data3": "[상세설명참조]",
                "data4": siil_origin,
                "data5": maker or "[상세설명참조]",
                "data6": "N",
                "data7": maker or "[상세설명참조]",
                "data8": as_phone or "[상세설명참조]",
            }
        ]

        # 인증정보 (기본: 해당없음)
        data["CertType"] = "C"

        # 사용자 임의분류 (검색필터명 기반)
        filter_name = product.get("_search_filter_name", "")
        if filter_name:
            data["MyCateName"] = f"SAMBA-WAVE/{filter_name}"

        return data


def _build_options(options: list[dict], default_stock: int = 999) -> list[dict]:
    """삼바웨이브 옵션 → EMP 옵션 변환.

    삼바웨이브 옵션 형식:
        [{name: "색상", value: "빨강", ...}, ...]
        또는
        [{option_name: "색상/사이즈", option_value: "빨강/M", ...}, ...]
    """
    emp_opts: list[dict] = []

    for opt in options:
        emp_opt: dict[str, str] = {"type": "SELECT"}

        # 옵션명 파싱 — 다양한 형식 대응
        opt_name = opt.get("option_name", "") or opt.get("name", "")
        opt_value = opt.get("option_value", "") or opt.get("value", "")

        # "/" 구분 형식 (색상/사이즈 → 빨강/M)
        names = opt_name.split("/") if "/" in opt_name else [opt_name]
        values = opt_value.split("/") if "/" in opt_value else [opt_value]

        for i, (n, v) in enumerate(zip(names[:3], values[:3]), 1):
            emp_opt[f"title{i}"] = n.strip()
            emp_opt[f"opt{i}"] = v.strip()

        # 옵션 가격
        opt_price = opt.get("option_price", 0) or opt.get("add_price", 0)
        emp_opt["price"] = str(int(opt_price))

        # 옵션 재고 (max_stock 제한 적용)
        opt_stock = opt.get("stock", opt.get("quantity", default_stock))
        if default_stock > 0:
            opt_stock = min(int(opt_stock), default_stock)
        if opt.get("is_sold_out") or opt.get("sold_out"):
            emp_opt["soldout"] = "1"
            emp_opt["stock"] = "0"
        else:
            emp_opt["soldout"] = "0"
            emp_opt["stock"] = str(int(opt_stock))

        emp_opt["weight"] = "0"
        emp_opt["manage_code"] = ""
        emp_opt["barcode_user"] = ""

        emp_opts.append(emp_opt)

    return emp_opts


_DOMESTIC_KEYWORDS = {"국내", "한국", "대한민국", "Korea"}
_ETC_KEYWORDS = {"기타", "해당없음", "없음", "미상"}


def _normalize_origin(origin: str | None) -> str:
    """원산지 값을 EMP 포맷(국가구분=시도=시군구)으로 정규화.

    입력 예시:
        "기타" → "기타=기타=기타"
        "국내" → "국내=기타=기타"
        "국내=서울=서울시" → 그대로
        "인도네시아" → "해외=인도네시아=인도네시아"
        "중국" → "해외=중국=중국"
        None / "" → "기타=기타=기타"
    """
    if not origin or not origin.strip():
        return "기타=기타=기타"
    origin = origin.strip()

    # 이미 "=" 포함된 완전한 형식
    parts = origin.split("=")
    if len(parts) >= 3:
        return origin
    if len(parts) == 2:
        return f"{parts[0]}={parts[1]}={parts[1]}"

    # 단일 값 — 국내/기타/해외 자동 판별
    if origin in _DOMESTIC_KEYWORDS:
        return "국내=기타=기타"
    if origin in _ETC_KEYWORDS:
        return "기타=기타=기타"
    # 그 외 국가명은 해외로 처리
    return f"해외={origin}={origin}"
