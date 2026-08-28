"""바이마(BUYMA) 일괄출품편집 CSV 업로드 클라이언트.

공식 PS-API 없이, 바이마 판매자센터의 「일괄 출품 편집(一括出品編集)」 내부
엔드포인트를 이용해 상품/재고를 일괄 등록·갱신한다.
인증은 KREAM 방식과 동일하게 로그인 세션 쿠키(buyma.com)를 사용한다.

업로드 흐름 (실측 리버스 엔지니어링, 2026-08-12):
1. GET  https://www.buyma.com/rorapi/sell/bulk/presigned_post
        ?name=<file>&type=items|colorsizes&without_images=false
        (Cookie 인증) → S3 presigned POST 파라미터 {url, fields}
2. POST <s3_url> (multipart/form-data: fields 전체 + CSV 파일) → 201 Created
3. 바이마가 S3 이벤트로 자동 처리 (별도 처리 트리거 요청 없음 = event-driven)

CSV 포맷은 판매자센터 「전항목」 다운로드로 확보한 실제 SL72 데이터 기준.
items.csv(111열) + colorsizes.csv(54열) 2개 파일을 각각 업로드한다.
"""

from __future__ import annotations

import csv
import io
from typing import Any

import httpx

from backend.utils.logger import logger


# ---------------------------------------------------------------------------
# CSV 열 정의 (전항목 다운로드로 확보한 실제 헤더, 순서 고정 — 변경 금지)
# ---------------------------------------------------------------------------

ITEMS_COLUMNS: list[str] = [
    "商品ID",
    "商品管理番号",
    "コントロール",
    "商品名",
    "ブランド",
    "ブランド名",
    "モデル",
    "カテゴリ",
    "シーズン",
    "テーマ",
    "単価",
    "買付可数量",
    "購入期限",
    "参考価格/通常出品価格",
    "参考価格",
    "商品コメント",
    "色サイズ補足",
    "タグ",
    "配送方法",
    "買付エリア",
    "買付都市",
    "買付ショップ",
    "発送エリア",
    "発送都市",
    "関税込み",
    "出品メモ",
    *[f"商品イメージ{i}" for i in range(1, 21)],  # 商品イメージ1~20
    *sum(
        ([f"ブランド品番{i}", f"ブランド品番識別メモ{i}"] for i in range(1, 11)),
        [],
    ),  # ブランド品番1~10 + 識別メモ
    *sum(
        ([f"買付先名{i}", f"買付先URL{i}", f"買付先説明{i}"] for i in range(1, 16)),
        [],
    ),  # 買付先名/URL/説明 1~15
]

COLORSIZES_COLUMNS: list[str] = [
    "商品ID",
    "商品管理番号",
    "商品名",
    "並び順",
    "サイズ名称",
    "サイズ単位",
    "検索用サイズ",
    "色名称",
    "色系統",
    "在庫ステータス",
    "手元に在庫あり数量",
    "色サイズリプレイス",
    # 이하 신체/사이즈 상세 치수 (신발은 대부분 공란, ヒール高 정도만 선택 입력)
    "着丈",
    "肩幅",
    "胸囲",
    "袖丈",
    "ウエスト",
    "ヒップ",
    "総丈",
    "幅",
    "股上",
    "股下",
    "もも周り",
    "すそ周り",
    "スカート丈",
    "トップ",
    "アンダー",
    "高さ",
    "ヒール高",
    "つつ周り",
    "足幅",
    "マチ",
    "持ち手",
    "ストラップ",
    "奥行",
    "縦",
    "横",
    "厚み",
    "長さ",
    "トップ縦",
    "トップ横",
    "円周",
    "手首周り",
    "文字盤縦",
    "文字盤横",
    "フレーム縦",
    "フレーム横",
    "レンズ縦",
    "レンズ横",
    "テンプル",
    "全長",
    "最大幅",
    "頭周り",
    "つば",
    "直径",
]


# ---------------------------------------------------------------------------
# ID 매핑 (SL72 실측값 + 확장 필요)
# ---------------------------------------------------------------------------

# 브랜드 ID (판매자센터 ID표에서 확장. 우선 실측 확인분만.)
BRAND_IDS: dict[str, str] = {
    "adidas": "105",
    "아디다스": "105",
}

# 색계통 ID (色系統). 실측: 그린=6. 나머지는 ID표에서 채워야 함.
COLOR_GROUP_IDS: dict[str, str] = {
    "그린": "6",
    "green": "6",
    "グリーン": "6",
    # TODO: 블랙/화이트/레드/블루/브라운/베이지 등 ID표에서 확장
}

# 매입/발송 지역 코드. 실측: 한국=2002003, 도시=000
AREA_KOREA = "2002003"
CITY_DEFAULT = "000"

# 카테고리 ID (실측: 레디스 스니커즈=3081)
CATEGORY_LADIES_SNEAKER = "3081"

# 관세込み: 1=관세부담없음(면세/우리부담), 0=구매자부담
KANZEI_INCLUDED = "1"

# 재고 스테이터스: 1=매수가능(주문 후 매입/무재고)
STOCK_STATUS_ORDERABLE = "1"

# 컨트롤 값: 신규/수정 게시
CONTROL_PUBLISH = "公開"


class BuymaBulkClient:
    """바이마 일괄출품편집 CSV 생성 + 업로드 (세션 쿠키 인증)."""

    PRESIGNED_URL = "https://www.buyma.com/rorapi/sell/bulk/presigned_post"

    HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Accept-Language": "ja,ko;q=0.9",
        "Referer": "https://www.buyma.com/my/sell/bulk/",
    }

    def __init__(self, cookie: str = "", shipping_method_id: str = "1091378") -> None:
        # 로그인 세션 쿠키 (확장앱이 로그인된 바이마 탭에서 추출)
        self.cookie = cookie
        # 계정별 배송방법 ID (실측 SL72=1091378, 계정마다 다름 → 설정값)
        self.shipping_method_id = shipping_method_id

    # ------------------------------------------------------------------
    # CSV 행 변환
    # ------------------------------------------------------------------

    def transform_items_row(
        self,
        product: dict[str, Any],
        *,
        manage_no: str,
        purchase_deadline: str,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """CollectedProduct → items.csv 한 행(dict).

        manage_no: 신규 등록 시 items↔colorsizes 연결키 (商品管理番号).
                   기존 상품 수정은 商品ID로 연결되지만, 신규는 商品ID가 없으므로
                   同一 商品管理番号로 두 파일을 묶는다.
        """
        s = settings or {}
        name = product.get("name") or ""
        brand = (product.get("brand") or "").strip()
        brand_id = BRAND_IDS.get(brand) or BRAND_IDS.get(brand.lower()) or ""
        # 単価는 엔화 판매가. 파이프라인이 시세 기반 목표가(_buyma_price_yen)를 세팅.
        # (없으면 sale_price 폴백 — 단, 원화가 들어가지 않게 반드시 엔가 세팅 필요)
        price = int(product.get("_buyma_price_yen") or product.get("sale_price") or 0)
        images = product.get("images") or []
        detail = product.get("detail_html") or product.get("comment") or f"{name}"

        row: dict[str, str] = {c: "" for c in ITEMS_COLUMNS}
        row["商品ID"] = str(product.get("buyma_item_id") or "")  # 신규는 공란
        row["商品管理番号"] = manage_no
        row["コントロール"] = CONTROL_PUBLISH
        row["商品名"] = name
        row["ブランド"] = brand_id
        row["ブランド名"] = s.get("brand_name") or brand
        row["モデル"] = str(s.get("model_id") or "0")
        row["カテゴリ"] = str(s.get("category_id") or CATEGORY_LADIES_SNEAKER)
        row["シーズン"] = "0"
        row["テーマ"] = "0"
        row["単価"] = str(price)
        row["買付可数量"] = str(
            product.get("_stock_total") or s.get("stock_total") or 1
        )
        row["購入期限"] = purchase_deadline  # YYYY-MM-DD
        row["参考価格/通常出品価格"] = "0"
        row["商品コメント"] = detail
        row["配送方法"] = self.shipping_method_id
        row["買付エリア"] = AREA_KOREA
        row["買付都市"] = CITY_DEFAULT
        row["発送エリア"] = AREA_KOREA
        row["発送都市"] = CITY_DEFAULT
        row["関税込み"] = KANZEI_INCLUDED

        # 이미지 URL (최대 20장). 공개 접근 가능한 URL이어야 바이마가 취득.
        for i, url in enumerate(images[:20], start=1):
            row[f"商品イメージ{i}"] = url

        # 품번 (선택) — 소싱 품번을 ブランド品番1에
        style = (product.get("style_code") or product.get("model_no") or "").strip()
        if style:
            row["ブランド品番1"] = style

        return row

    def transform_colorsizes_rows(
        self,
        product: dict[str, Any],
        *,
        manage_no: str,
    ) -> list[dict[str, str]]:
        """CollectedProduct 옵션 → colorsizes.csv 행 리스트 (사이즈별).

        옵션 스키마: [{name/size, price, stock, isSoldOut, color?}]
        색계통(色系統)은 색상명으로 매핑, 미매칭 시 공란(수동확인).
        """
        name = product.get("name") or ""
        color_name = (product.get("color") or "").strip()
        color_group = (
            COLOR_GROUP_IDS.get(color_name)
            or COLOR_GROUP_IDS.get(color_name.lower())
            or ""
        )
        options = product.get("options") or []

        rows: list[dict[str, str]] = []
        order = 0
        for opt in options:
            if opt.get("isSoldOut"):
                continue
            size_label = str(opt.get("name") or opt.get("size") or "").strip()
            if not size_label:
                continue
            order += 1
            # 사이즈 정규화: 한국 mm(예 "230") → 표시 cm(23.0) + 검색용 mm(230)
            search_size, display_size = self._normalize_shoe_size(size_label)

            r: dict[str, str] = {c: "" for c in COLORSIZES_COLUMNS}
            r["商品ID"] = str(product.get("buyma_item_id") or "")
            r["商品管理番号"] = manage_no
            r["商品名"] = name
            r["並び順"] = str(order)
            r["サイズ名称"] = display_size
            r["サイズ単位"] = "cm"
            r["検索用サイズ"] = search_size
            r["色名称"] = opt.get("color") or color_name
            r["色系統"] = opt.get("color_group") or color_group
            r["在庫ステータス"] = STOCK_STATUS_ORDERABLE  # 매수가능(무재고)
            # 手元に在庫あり数量: 무재고이므로 공란(0)
            rows.append(r)
        return rows

    @staticmethod
    def _normalize_shoe_size(label: str) -> tuple[str, str]:
        """신발 사이즈 라벨 → (검색용 mm, 표시 cm).

        "230" → ("230", "23.0") / "23.0" → ("230", "23.0") / "23" → ("230","23.0")
        """
        digits = "".join(ch for ch in label if ch.isdigit() or ch == ".")
        try:
            val = float(digits)
        except ValueError:
            return label, label
        mm = int(round(val * 10)) if val < 40 else int(round(val))  # cm→mm
        cm = mm / 10
        return str(mm), f"{cm:.1f}"

    # ------------------------------------------------------------------
    # CSV 생성 (Shift-JIS, 바이마 업로드 규격)
    # ------------------------------------------------------------------

    @staticmethod
    def _to_csv_bytes(columns: list[str], rows: list[dict[str, str]]) -> bytes:
        """행 dict 리스트 → CSV bytes (UTF-8, QUOTE_ALL).

        바이마 업로드는 sjis/utf8 모두 허용. Shift-JIS는 한글(색상명 등) 인코딩이
        불가하므로 UTF-8 사용(BOM 없음 — 헤더 매칭 보존). 파일명도 .utf8.csv로 맞춘다.
        """
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf, fieldnames=columns, extrasaction="ignore", quoting=csv.QUOTE_ALL
        )
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
        return buf.getvalue().encode("utf-8")

    def generate_items_csv(self, rows: list[dict[str, str]]) -> bytes:
        return self._to_csv_bytes(ITEMS_COLUMNS, rows)

    def generate_colorsizes_csv(self, rows: list[dict[str, str]]) -> bytes:
        return self._to_csv_bytes(COLORSIZES_COLUMNS, rows)

    # ------------------------------------------------------------------
    # 업로드 (presigned → S3, event-driven 자동처리)
    # ------------------------------------------------------------------

    async def _get_presigned(
        self, client: httpx.AsyncClient, filename: str, ftype: str
    ) -> dict[str, Any]:
        """S3 presigned POST 파라미터 획득 (type: 'items' | 'colorsizes')."""
        resp = await client.get(
            self.PRESIGNED_URL,
            params={"name": filename, "type": ftype, "without_images": "false"},
            headers={**self.HEADERS, "Cookie": self.cookie},
        )
        if resp.status_code != 200:
            raise BuymaBulkError(
                f"presigned_post 실패({ftype}): HTTP {resp.status_code} "
                f"{resp.text[:200]}"
            )
        data = resp.json()
        if not data.get("url") or not data.get("fields"):
            raise BuymaBulkError(f"presigned 응답 형식 오류: {str(data)[:200]}")
        return data

    async def _upload_s3(
        self,
        client: httpx.AsyncClient,
        presigned: dict[str, Any],
        csv_bytes: bytes,
        filename: str,
    ) -> None:
        """S3에 CSV 업로드 (multipart: fields 전체 + file). 201 기대."""
        fields = {k: str(v) for k, v in presigned["fields"].items()}
        resp = await client.post(
            presigned["url"],
            data=fields,
            files={"file": (filename, csv_bytes, "text/csv")},
        )
        # S3는 success_action_status=201 → 201 반환
        if resp.status_code not in (200, 201, 204):
            raise BuymaBulkError(
                f"S3 업로드 실패: HTTP {resp.status_code} {resp.text[:300]}"
            )

    async def upload(self, csv_bytes: bytes, ftype: str) -> dict[str, Any]:
        """CSV 1개 업로드 (presigned → S3). ftype: 'items' | 'colorsizes'.

        업로드 성공(201) 후 바이마가 S3 이벤트로 자동 처리한다.
        """
        if not self.cookie:
            return {"success": False, "message": "바이마 세션 쿠키가 없습니다."}
        filename = f"{ftype}.utf8.csv"
        timeout = httpx.Timeout(60.0, connect=15.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                presigned = await self._get_presigned(client, filename, ftype)
                await self._upload_s3(client, presigned, csv_bytes, filename)
            logger.info(f"[바이마] {ftype} CSV 업로드 완료 ({len(csv_bytes)} bytes)")
            return {"success": True, "message": f"{ftype} 업로드 완료(자동처리 대기)"}
        except BuymaBulkError as e:
            logger.error(f"[바이마] 업로드 실패: {e}")
            return {"success": False, "message": str(e)}

    async def upload_products(
        self,
        products: list[dict[str, Any]],
        *,
        purchase_deadline: str,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """상품 목록 → items + colorsizes CSV 생성 후 순차 업로드.

        neing manage_no로 items↔colorsizes를 연결(신규 등록).
        colorsizes를 먼저 올릴지 items를 먼저 올릴지는 바이마 처리 순서 검증 필요
        (현재는 items → colorsizes 순).
        """
        item_rows: list[dict[str, str]] = []
        cs_rows: list[dict[str, str]] = []
        for p in products:
            manage_no = str(
                p.get("manage_no")
                or p.get("style_code")
                or p.get("id")
                or p.get("site_product_id")
                or ""
            )
            item_rows.append(
                self.transform_items_row(
                    p,
                    manage_no=manage_no,
                    purchase_deadline=purchase_deadline,
                    settings=settings,
                )
            )
            cs_rows.extend(self.transform_colorsizes_rows(p, manage_no=manage_no))

        items_csv = self.generate_items_csv(item_rows)
        cs_csv = self.generate_colorsizes_csv(cs_rows)

        r1 = await self.upload(items_csv, "items")
        if not r1.get("success"):
            return r1
        r2 = await self.upload(cs_csv, "colorsizes")
        return {
            "success": r1.get("success") and r2.get("success"),
            "items": r1,
            "colorsizes": r2,
            "message": f"상품 {len(products)}건 업로드 (자동처리 대기)",
        }


class BuymaBulkError(Exception):
    """바이마 일괄 업로드 에러."""

    pass
