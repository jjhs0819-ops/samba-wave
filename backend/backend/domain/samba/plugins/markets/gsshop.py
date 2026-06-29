"""GS샵 마켓 플러그인.

기존 dispatcher._handle_gsshop + _transform_for_gsshop 로직을 플러그인 구조로 추출.
인증 로드는 base._load_auth 가 처리하므로 execute 에서는 creds dict 사용.
"""

from __future__ import annotations

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.utils import add_lazy_loading
from backend.utils.logger import logger


async def _get_setting(session, key: str) -> Any:
    """samba_settings 테이블에서 설정값 조회 후 즉시 커밋 — idle in transaction 방지."""
    from backend.domain.samba.forbidden.model import SambaSettings
    from sqlmodel import select

    stmt = select(SambaSettings).where(SambaSettings.key == key)
    result = await session.execute(stmt)
    row = result.scalars().first()
    val = row.value if row else None
    try:
        await session.commit()
    except Exception:
        pass
    return val


_GS_CATEGORY_MAP_CACHE: dict[str, str] | None = None
# 계정별 전시매장 목록 캐시 (getAllSectList)
_GS_SECT_CACHE: dict[str, list[dict]] = {}
# 계정별 상품분류코드 목록 캐시 (SupSendPrdClsInfo)
_GS_CLS_CACHE: dict[str, list[dict]] = {}


def _load_gs_category_map() -> dict[str, str]:
    """소싱카테고리 → "prdClsCd|sectId" 기본 매핑(레포 커밋 JSON). 모듈 레벨 캐시."""
    global _GS_CATEGORY_MAP_CACHE
    if _GS_CATEGORY_MAP_CACHE is None:
        import json
        import os

        path = os.path.join(os.path.dirname(__file__), "gsshop_category_map.json")
        try:
            with open(path, encoding="utf-8") as f:
                _GS_CATEGORY_MAP_CACHE = json.load(f)
        except Exception:
            _GS_CATEGORY_MAP_CACHE = {}
    return _GS_CATEGORY_MAP_CACHE


def _gs_valid_sect(category_id: Any) -> bool:
    """category_id에 유효한 sectId(숫자 전시매장)가 있는지.
    'B43071903|1662742' → True, 'B43071903'/'B43071903|' → False, '1662742' → True.
    """
    s = str(category_id or "")
    if not s:
        return False
    if "|" in s:
        return s.split("|", 1)[1].strip().isdigit()
    return s.strip().isdigit()


# 키워드 → "prdClsCd|sectId" (소싱처 무관 카테고리 폴백). 순서 = 구체적인 것 먼저.
# prdClsCd/sectId 값은 gsshop_category_map.json(검증된 67종)과 동일 코드 사용.
_GS_KEYWORD_RULES: list[tuple[tuple[str, ...], str]] = [
    # ── 신발 (B25) ──
    (("러닝화", "런닝화", "조깅화", "마라톤", "트레일러닝"), "B25030109|1734345"),
    (("아쿠아", "워터슈즈", "물놀이"), "B25030111|1663466"),
    (("샌들", "슬리퍼", "슬라이드", "쪼리", "플립플랍", "뮬"), "B25010105|1663468"),
    (("부츠", "워커"), "B25010103|1663471"),
    (
        (
            "스니커즈",
            "운동화",
            "스포츠화",
            "캐주얼화",
            "라이프스타일화",
            "단화",
            "로퍼",
            "구두",
            "스케이트",
            "발레",
            "헬스화",
            "피트니스화",
            "신발",
            "슈즈",
        ),
        "B25030115|1663470",
    ),
    # ── 하의 (B43071903 / 레깅스 B43071301) ──
    (("레깅스",), "B43071301|1719598"),
    (("숏팬츠", "숏 팬츠", "반바지", "쇼츠", "하프팬츠"), "B43071903|1662743"),
    (
        ("팬츠", "바지", "슬랙스", "조거", "데님", "하의", "트라우저"),
        "B43071903|1662742",
    ),
    # ── 아우터 (B43071905 / 패딩 B43130505 / 카디건 B43130519) ──
    (("패딩", "다운", "헤비 아우터", "푸퍼"), "B43130505|1662739"),
    (("카디건",), "B43130519|1662744"),
    (("베스트", "조끼"), "B43071905|1662745"),
    (("후드집업", "후드 집업", "집업"), "B43071905|1734349"),
    (("아노락", "코치 재킷", "나일론 재킷"), "B43071905|1662741"),
    (
        (
            "재킷",
            "자켓",
            "아우터",
            "코트",
            "점퍼",
            "블루종",
            "플리스",
            "뽀글이",
            "바람막이",
            "트랙탑",
            "윈드브레이커",
            "패딩베스트",
        ),
        "B43071905|1662744",
    ),
    # ── 상의 (B43071907 / 니트 B43130503) ──
    (("후드티", "후드 티", "후디"), "B43071907|1734349"),
    (("맨투맨", "스웨트셔츠", "스웨트"), "B43071907|1662740"),
    (("니트", "스웨터"), "B43130503|1662740"),
    (
        (
            "티셔츠",
            "반소매",
            "긴소매",
            "셔츠",
            "블라우스",
            "민소매",
            "나시",
            "브라탑",
            "상의",
        ),
        "B43071907|1662747",
    ),
    # ── 가방 (정보고시 동적조회·전시매장 prdDispYn=Y, 등록검증 완료) ──
    (("백팩", "배낭"), "B69050105|1734355"),
    (("크로스백", "메신저백"), "B69050115|1663438"),
    (("숄더백",), "B69050109|1663437"),
    (("토트백", "서류가방"), "B69050117|1663436"),
    (
        ("힙색", "웨이스트백", "벨트백", "슬링백", "보스턴백", "더플백",
         "여행가방", "에코백", "가방"),
        "B69050105|1734355",
    ),
    # ── 잡화 (그룹13 패션잡화 정보고시, 등록검증 완료) ──
    (("양말", "삭스"), "B43071915|1660957"),
    (("모자", "캡", "비니", "버킷", "햇", "볼캡", "썬캡"), "B43071901|1660954"),
    (("장갑", "글러브"), "B43071913|1660958"),
    (("머플러", "스카프", "목도리", "넥워머", "워머"), "B43150301|1661269"),
]


def _gs_keyword_category(text: str) -> str:
    """카테고리/상품 텍스트의 키워드로 GS 분류 추정 (소싱처 무관)."""
    t = str(text or "")
    if not t:
        return ""
    for keywords, code in _GS_KEYWORD_RULES:
        if any(kw in t for kw in keywords):
            return code
    return ""


async def _find_best_sect_id(client: Any, prd_cls_cd: str) -> int:
    """prdClsCd 이름 기반으로 GS샵 전시매장 sectId 자동 매칭. 계정별 캐시 사용."""
    sup_cd = client.sup_cd

    if sup_cd not in _GS_SECT_CACHE:
        try:
            r = await client.get_categories()
            _GS_SECT_CACHE[sup_cd] = (r.get("data") or {}).get("resultList") or []
        except Exception:
            _GS_SECT_CACHE[sup_cd] = []

    if sup_cd not in _GS_CLS_CACHE:
        try:
            r = await client.get_product_categories()
            _GS_CLS_CACHE[sup_cd] = (r.get("data") or {}).get("resultList") or []
        except Exception:
            _GS_CLS_CACHE[sup_cd] = []

    sections = _GS_SECT_CACHE[sup_cd]
    cls_list = _GS_CLS_CACHE[sup_cd]
    if not sections or not cls_list:
        return 0

    # prd_cls_cd에서 각 레벨 이름 추출 (세부→광범위 순)
    target_names: list[str] = []
    for item in cls_list:
        if item.get("dtlClsCd") == prd_cls_cd:
            for field in ["dtlClsNm", "smlClsNm", "midClsNm", "lrgClsNm"]:
                nm = str(item.get(field) or "").strip()
                if nm:
                    target_names.append(nm)
            break

    if not target_names:
        return 0

    def _norm(s: str) -> str:
        return s.replace(" ", "").replace("/", "").replace("·", "").lower()

    best_id = 0
    best_score = 0
    for s in sections:
        sect_nm = s.get("sectNm", "")
        sect_id = int(s.get("sectId") or 0)
        if not sect_id:
            continue
        snorm = _norm(sect_nm)
        for rank, target in enumerate(target_names):
            tnorm = _norm(target)
            if tnorm and (tnorm in snorm or snorm in tnorm):
                score = len(target_names) - rank  # 세부 이름일수록 높은 점수
                if score > best_score:
                    best_score = score
                    best_id = sect_id
                break

    return best_id


async def _resolve_gs_category_id(
    session: Any, product: dict[str, Any], category_id: str
) -> str:
    """소싱 카테고리로 GS 분류(prdClsCd|sectId) 결정 — 소싱처 무관.

    1) 이미 유효한 sectId 있으면 그대로
    2) 정확매칭: 레포 JSON(gsshop_category_map.json) + DB 설정(gsshop_category_map)
    3) 키워드매칭: 카테고리(없으면 상품명) 키워드로 추정 (모든 소싱처 커버)
    부분값(prdClsCd만, sectId 없음)도 2~3으로 full 'prdClsCd|sectId' 보완.
    매칭 실패 시 원본 유지 — 무리한 기본분류로 오등록하지 않는다.
    """
    if _gs_valid_sect(category_id):
        return category_id

    src_cat = str(product.get("category") or "").strip()

    # 2) 정확매칭 (sectId 있는 것만 채택)
    if src_cat:
        cat_map = dict(_load_gs_category_map())
        db_map = await _get_setting(session, "gsshop_category_map")
        if isinstance(db_map, dict):
            cat_map.update(db_map)
        matched = cat_map.get(src_cat)
        if matched and _gs_valid_sect(matched):
            logger.info(f"[GS샵] 카테고리 정확매칭: '{src_cat}' → {matched}")
            return str(matched)

    # 3) 키워드매칭 (카테고리 우선, 없으면 상품명)
    kw = _gs_keyword_category(src_cat) or _gs_keyword_category(
        product.get("name") or ""
    )
    if kw:
        logger.info(
            f"[GS샵] 카테고리 키워드매칭: '{src_cat or product.get('name')}' → {kw}"
        )
        return kw

    logger.warning(
        f"[GS샵] 카테고리 매칭 실패 (소싱카테고리='{src_cat}') — 키워드 룰 추가 필요"
    )
    return category_id


def _build_attr_prd_list(
    options: list[dict[str, Any]],
    sale_str_dtm: int,
    sale_end_dtm: int = 29991231235959,
    brand: str = "",
) -> list[dict[str, Any]]:
    """product options → GS샵 V3 attrPrdList 변환.

    options 구조: {"no": int, "name": str, "price": int, "stock": int, "isSoldOut": bool}
    """
    result = []
    for opt in options:
        name = str(opt.get("name") or "").strip()
        if not name:
            continue
        stock = int(opt.get("stock") or 0)
        is_sold_out = opt.get("isSoldOut", False) or stock <= 0
        result.append(
            {
                "attrPrdListSupAttrPrdCd": str(opt.get("no") or name)[:50],
                "attrPrdListSaleStrDtm": sale_str_dtm,
                "attrPrdListSaleEndDtm": sale_end_dtm,
                "attrPrdListAttrVal1": name,
                "attrPrdListAttrVal2": "None",
                "attrPrdListAttrVal3": "None",
                "attrPrdListAttrVal4": "None",
                "attrPrdListOrgpNm": "국내",
                "attrPrdListMnfcCoNm": brand or "",
                "attrPrdListSafeStockQty": max(0, stock),
                "attrPrdListTempoutYn": "Y" if is_sold_out else "N",
                "attrPrdListOrdPsblQty": 0 if is_sold_out else max(1, stock),
            }
        )
    return result


_ORIGIN_KO = {
    "china": "중국",
    "vietnam": "베트남",
    "korea": "대한민국",
    "indonesia": "인도네시아",
    "cambodia": "캄보디아",
    "bangladesh": "방글라데시",
    "india": "인도",
    "thailand": "태국",
    "myanmar": "미얀마",
    "philippines": "필리핀",
    "taiwan": "대만",
    "japan": "일본",
}


def _truncate_prdnm(name: str, max_bytes: int = 30) -> str:
    """GS 송장명(prdNm)=VARCHAR2(30)=30바이트. 특수문자 제거 후 한글 글자경계 안 깨지게 절단.
    노출상품명(prdNmChgExposPrdNm, 240자)은 풀로 유지하고 송장명만 줄인다.
    GS 송장명은 콜론/슬래시 등 특수문자 불가 → 공백으로 치환.
    """
    import re

    s = re.sub(r"[:/\\|<>\"'~^*]", " ", name)
    s = re.sub(r"\s+", " ", s).strip()
    out = ""
    for ch in s:
        try:
            nb = len((out + ch).encode("euc-kr"))
        except UnicodeEncodeError:
            nb = len((out + ch).encode("utf-8"))
        if nb > max_bytes:
            break
        out += ch
    return out.strip() or s[:15]


_GOV_ITEMS_CACHE: dict[str, list[dict[str, Any]] | None] = {}


async def _resolve_gov_items(
    client: Any, category_id: str, gs_settings: dict[str, Any] | None
) -> list[dict[str, Any]] | None:
    """분류 상세조회(getPrdClsDtlInfo)로 prdClsCd의 정보고시 항목 목록을 받는다.
    분류별 모듈 캐시. 실패 시 None(→ _build_gov_publs 가 의류/신발 폴백).
    이걸로 의류·신발뿐 아니라 가방(12)·패션잡화(13) 등 모든 정보고시 그룹 자동 대응.
    """
    cid = str(category_id or "")
    if "|" in cid:
        prd_cls = cid.split("|", 1)[0].strip()
    elif cid and not cid.strip().isdigit():
        prd_cls = cid.strip()
    else:
        prd_cls = ""
    prd_cls = prd_cls or str((gs_settings or {}).get("prdClsCd") or "").strip()
    if not prd_cls:
        return None
    if prd_cls in _GOV_ITEMS_CACHE:
        return _GOV_ITEMS_CACHE[prd_cls]
    items: list[dict[str, Any]] | None = None
    try:
        r = await client.get_prd_cls_dtl_info(prd_cls)
        data = r.get("data") or {}
        if isinstance(data.get("data"), dict):
            data = data["data"]
        grps = data.get("govPublsGrpList") or []
        if grps:
            items = grps[0].get("govPublsGrpItmList") or None
            logger.info(
                f"[GS샵] 정보고시 그룹 동적조회: {prd_cls} → "
                f"{grps[0].get('govPublsPrdGrpNm')} ({len(items or [])}항목)"
            )
    except Exception as e:
        logger.warning(f"[GS샵] 정보고시 그룹 조회 실패({prd_cls}): {e}")
    _GOV_ITEMS_CACHE[prd_cls] = items
    return items


def _build_gov_publs(
    product: dict[str, Any],
    brand: str,
    prd_cls_cd: str,
    gov_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """정보고시 — 분류(prdClsCd)별 그룹. 수집데이터 우선, 없으면 '상품 페이지 참조'.

    gov_items(분류 상세조회 getPrdClsDtlInfo 결과)가 있으면 **항목명 기반으로 동적**
    구성 → 의류·신발뿐 아니라 가방(12)·패션잡화(13) 등 모든 정보고시 그룹 자동 대응.
    없으면(API 실패) 의류(10)/신발(11) 하드코딩으로 폴백.
    """

    def g(v: Any, default: str = "상품 페이지 참조") -> str:
        s = str(v or "").strip()
        return s if s else default

    origin = str(product.get("origin") or "").strip()
    origin_ko = _ORIGIN_KO.get(origin.lower(), origin) if origin else "상품 페이지 참조"
    material = g(product.get("material"))
    color = g(product.get("color"))
    maker = g(product.get("manufacturer") or brand)
    care = g(product.get("care_instructions"))
    as_phone = g(product.get("as_phone"))
    quality = g(
        product.get("quality_guarantee"), "관련 법령 및 소비자분쟁해결기준에 따름"
    )
    size = g(product.get("size_notice"))
    _cat = str(product.get("category") or "").strip()
    kind = g(_cat.split(">")[-1].strip() if _cat else "")

    # 동적: 분류 상세조회 항목명으로 매핑 (모든 정보고시 그룹 대응)
    if gov_items:

        def _content(itm_name: str) -> str:
            n = str(itm_name or "")
            if "소재" in n or "조성" in n:
                return material
            if "색상" in n:
                return color
            if "굽" in n or "높이" in n:
                return g(product.get("heel_height"), "해당없음")
            if "발길이" in n or "사이즈" in n or "치수" in n or "크기" in n:
                return size
            if "제조국" in n or "원산지" in n:
                return origin_ko
            if "제조자" in n or "수입자" in n or "제조원" in n or "수입원" in n:
                return maker
            if "제조연월" in n or "제조일" in n:
                return g(product.get("manufacture_date"))
            if "세탁" in n or "취급" in n:
                return care
            if "A/S" in n or "AS" in n or "전화" in n or "책임자" in n:
                return as_phone
            if "품질" in n or "보증" in n:
                return quality
            if "종류" in n:
                return kind
            return "상품 페이지 참조"

        out = []
        for it in gov_items:
            cd = str(it.get("govPublsItmCd") or "").strip()
            if cd:
                out.append(
                    {
                        "govPublsItmCd": cd,
                        "govPublsItmCntnt": _content(it.get("govPublsItmNm")),
                    }
                )
        if out:
            return out

    if str(prd_cls_cd).startswith("B25"):  # 신발 (그룹11: 1101~1109)
        return [
            {"govPublsItmCd": "1101", "govPublsItmCntnt": material},
            {"govPublsItmCd": "1102", "govPublsItmCntnt": color},
            {
                "govPublsItmCd": "1103",
                "govPublsItmCntnt": g(product.get("size_notice")),
            },
            {
                "govPublsItmCd": "1104",
                "govPublsItmCntnt": g(product.get("heel_height"), "해당없음"),
            },
            {"govPublsItmCd": "1105", "govPublsItmCntnt": maker},
            {"govPublsItmCd": "1106", "govPublsItmCntnt": origin_ko},
            {"govPublsItmCd": "1107", "govPublsItmCntnt": quality},
            {"govPublsItmCd": "1108", "govPublsItmCntnt": as_phone},
            {"govPublsItmCd": "1109", "govPublsItmCntnt": care},
        ]
    # 의류 (그룹10: 1001~1009)
    return [
        {"govPublsItmCd": "1001", "govPublsItmCntnt": material},
        {"govPublsItmCd": "1002", "govPublsItmCntnt": color},
        {"govPublsItmCd": "1003", "govPublsItmCntnt": g(product.get("size_notice"))},
        {"govPublsItmCd": "1004", "govPublsItmCntnt": maker},
        {"govPublsItmCd": "1005", "govPublsItmCntnt": origin_ko},
        {"govPublsItmCd": "1006", "govPublsItmCntnt": care},
        {
            "govPublsItmCd": "1007",
            "govPublsItmCntnt": g(product.get("manufacture_date")),
        },
        {"govPublsItmCd": "1008", "govPublsItmCntnt": quality},
        {"govPublsItmCd": "1009", "govPublsItmCntnt": as_phone},
    ]


def _transform_for_gsshop(
    product: dict[str, Any],
    category_id: str,
    sub_sup_cd: str = "",
    gs_margin_rate: int = 0,
    gs_settings: dict[str, Any] | None = None,
    gov_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """수집 상품 → GS샵 V3 ProductV3 형식 변환.

    gs_settings 는 policy.market_policies["GS샵"]["gsSettings"] 에서 전달.
    필수 코드값(brandCd, prdClsCd, dlvsCoCd, operMdId 등)은 여기서 읽는다.
    govPublsItmList: 의류 기준 코드 1001~1009 사용 (getPrdClsDtlInfo API 확인값).
    """
    from datetime import datetime, timezone, timedelta

    gs = gs_settings or {}
    images = product.get("images") or []
    sale_price = int(product.get("sale_price") or 0)
    brand = str(product.get("brand") or "")
    name = str(product.get("name") or "")

    # 브랜드코드 — 정책 gsSettings.brands[](멀티선택)에서 상품 브랜드와 매칭.
    # 정책 UI는 brands 배열로 저장하는데 legacy 단일 brandCd만 읽으면 비어서 GS 등록 실패함.
    def _resolve_brand_cd() -> str:
        single = str(gs.get("brandCd") or "")
        brands = gs.get("brands") or []
        if not brands:
            return single

        def _bn(b: dict[str, Any]) -> str:
            return str(b.get("brandNm") or "").strip().lower().replace(" ", "")

        pb = brand.strip().lower().replace(" ", "")
        pn = name.lower().replace(" ", "")
        # 1) 정확 일치 최우선 (전체 스캔) — "나이키" 상품이 "나이키 키즈"에 잘못 매칭되는 것 방지
        if pb:
            for b in brands:
                if _bn(b) and _bn(b) == pb:
                    return str(b.get("brandCd") or "")
        # 2) 정책 브랜드명이 상품 브랜드명에 포함 (예: 상품 "나이키골프" ⊃ 정책 "나이키").
        #    구체적(긴) 브랜드명 우선해 "나이키 키즈"가 "나이키"보다 먼저 매칭되게.
        #    주의: 반대방향(상품브랜드 ⊂ 정책브랜드)은 "나이키"→"나이키 키즈" 오매칭이라 제외.
        if pb:
            for b in sorted(brands, key=lambda x: -len(_bn(x))):
                if _bn(b) and _bn(b) in pb:
                    return str(b.get("brandCd") or "")
        # 3) 상품명에 정책 브랜드명 포함 (긴 것 우선)
        for b in sorted(brands, key=lambda x: -len(_bn(x))):
            if _bn(b) and _bn(b) in pn:
                return str(b.get("brandCd") or "")
        # 4) 폴백: legacy 단일 brandCd → 브랜드가 1개뿐일 때만 그 브랜드.
        #    매칭 실패 + 다중 브랜드면 임의 선택(오등록)하지 말고 빈값 → GS가 brandCd 필수로 막게 둠.
        if single:
            return single
        if len(brands) == 1:
            return str((brands[0] or {}).get("brandCd") or "")
        return ""

    brand_cd = _resolve_brand_cd()

    # 판매 기간 (KST 현재 ~ 9999-12-31)
    kst = timezone(timedelta(hours=9))
    now_dtm = int(datetime.now(kst).strftime("%Y%m%d%H%M%S"))
    end_dtm = 29991231235959

    # 공급가 계산 — 마진율 있으면 역산 후 10원 단위 버림 (GS API 원단위 거부)
    if gs_margin_rate:
        sup_prc = int(sale_price * (100 - gs_margin_rate) / 100 / 10) * 10
    else:
        sup_prc = sale_price

    # 옵션 → V3 attrPrdList
    options = product.get("options") or []
    attr_prd_list = _build_attr_prd_list(options, now_dtm, end_dtm, brand)

    # 첫 옵션 타입명 추출 (상품 유형 라벨)
    first_opt_name = ""
    if options:
        first_nm = str(options[0].get("name") or "")
        # "사이즈: M" 형태면 "사이즈"만 추출
        first_opt_name = first_nm.split(":")[0].strip() if ":" in first_nm else "사이즈"

    # 전시매장 — sectid 정수형
    # category_id 형식: "B43071905|1662750" (prdClsCd|sectId) 또는 숫자(sectId만)
    prd_sect_list: list[dict[str, Any]] = []
    category_prd_cls_cd: str = ""
    if category_id:
        if "|" in str(category_id):
            parts = str(category_id).split("|", 1)
            category_prd_cls_cd = parts[0].strip()
            sect_id_str = parts[1].strip()
        elif str(category_id).upper().startswith("B"):
            # B코드(prdClsCd)만 있는 경우 — sectId 없음
            category_prd_cls_cd = str(category_id).strip()
            sect_id_str = ""
        else:
            sect_id_str = str(category_id)
        try:
            sect_id = int(sect_id_str)
        except (ValueError, TypeError):
            sect_id = 0
        if sect_id:
            prd_sect_list.append(
                {
                    "prdSectListSectid": sect_id,
                    "prdSectListSectGbn": "S",
                    "prdSectListSectStdYn": "Y",
                }
            )

    # 협력사 상품코드 — style_code > site_product_id > id 순
    sup_prd_cd = str(
        product.get("style_code")
        or product.get("site_product_id")
        or product.get("id")
        or ""
    )

    detail_html = product.get("detail_html") or f"<p>{name}</p>"

    # 이미지 URL (리스트)
    img_urls: list[str] = []
    for img in images:
        url = img if isinstance(img, str) else (img.get("url") or img.get("src") or "")
        if url:
            img_urls.append(url)

    img_info: dict[str, Any] = {}
    if img_urls:
        img_info["prdCntntListCntntUrlNm"] = img_urls

    # 교환/반품비
    rtp_amt = int(gs.get("rtpAmt") or 5000)
    exch_amt = int(gs.get("exchAmt") or 5000)

    # 출고일 (당일=0이면 당일출고마감시간 입력 가능)
    std_rels_ddcnt = int(gs.get("stdRelsDdcnt") or 1)
    base_add_info: dict[str, Any] = {
        "prdNm": _truncate_prdnm(name),
        "brandCd": brand_cd,
        "prdClsCd": category_prd_cls_cd or gs.get("prdClsCd") or "",
        # 3100=직송(설치), 3200=직송(택배) — 택배사(dlvsCoCd)는 직송(택배)일 때만 적용됨
        "dlvPickMthodCd": int(gs.get("dlvPickMthodCd") or 3200),
        "dlvsCoCd": str(gs.get("dlvsCoCd") or "DH"),
        "saleStrDtm": now_dtm,
        "saleEndDtm": end_dtm,
        "mnfcCoNm": gs.get("mnfcCoNm") or brand,
        "operMdId": int(gs.get("operMdId") or 0),
        "orgpNm": gs.get("orgpNm") or "국내",
        # 02=일반(택배)
        "ordPrdTypCd": str(gs.get("ordPrdTypCd") or "02"),
        # 02=과세
        "taxTypCd": str(gs.get("taxTypCd") or "02"),
        # S=단일옵션
        "prdTypCd": str(gs.get("prdTypCd") or "S"),
        "chrDlvYn": "N",
        "chrDlvcAmt": 0,
        "shipLimitAmt": 0,
        "exchRtpChrYn": "Y",
        "rtpAmt": rtp_amt,
        "exchAmt": exch_amt,
        "chrDlvAddYn": "N",
        # 도서산간/제주 배송가능(Y) + 추가배송비·반품비·교환비 5000원(직송택배라 추가유료배송 가능)
        "ilndDlvPsblYn": "Y",
        "ilndChrDlvYn": "Y",
        "ilndChrDlvcAmt": 5000,
        "ilndExchRtpChrYn": "Y",
        "ilndRtpAmt": 5000,
        "ilndExchAmt": 5000,
        "jejuDlvPsblYn": "Y",
        "jejuChrDlvYn": "Y",
        "jejuChrDlvcAmt": 5000,
        "jejuExchRtpChrYn": "Y",
        "jejuRtpAmt": 5000,
        "jejuExchAmt": 5000,
        "bundlDlvCd": str(gs.get("bundlDlvCd") or "A01"),
        "clerncUniqSignNeedYn": "N",
        "openAftRtpNoadmtYn": "Y",
        "prdRelspAddrCd": str(gs.get("prdRelspAddrCd") or "0001"),
        "prdRetpAddrCd": str(gs.get("prdRetpAddrCd") or "0001"),
        "ordMnfcYn": "N",
        "attrTypExposCd": "L",
        "adultCertYn": "N",
        "frmlesPrdTypCd": "N",
        "attrTypNm1": first_opt_name or "사이즈",
        "paraImPrdYn": "N",
        "prdBaseCmposCntnt": _truncate_prdnm(name),
        "orgprdPkgCnt": 1,
        "prdUnitValCd40": "A01",
        "prdUnitValCd20": "B01",
        # 환불유형 10=상품확인 후 환불, 20=즉시환불 → 상품확인 후 환불
        "rfnTypCd": 10,
        "supTmDlvCntnt": str(gs.get("supTmDlvCntnt") or "출고 2~3일"),
        "stdRelsDdcnt": std_rels_ddcnt,
        "prdStoreMthodCd": 10,
    }
    # 당일출고(0)인 경우에만 마감시간 입력
    if std_rels_ddcnt == 0 and gs.get("thedayRelsOrdDedlnTime") is not None:
        base_add_info["thedayRelsOrdDedlnTime"] = int(gs["thedayRelsOrdDedlnTime"])

    payload: dict[str, Any] = {
        "supPrdCd": sup_prd_cd,
        "subSupCd": sub_sup_cd if sub_sup_cd else None,
    }
    payload.update(
        {
            "prdBaseAddInfo": base_add_info,
            "prdPrcInfo": {
                "prdPrcValidStrDtm": now_dtm,
                "prdPrcValidEndDtm": end_dtm,
                "prdPrcSalePrc": sale_price,
                "prdPrcSupGivRtamt": sup_prc,
                "prdPrcSupGivRtamtCd": "01",
            },
            "prdNmChgInfo": {
                "prdNmChgExposPrdNm": name,
                "prdNmChgValidStrDtm": now_dtm,
                "prdNmChgValidEndDtm": end_dtm,
            },
            "prdImgInfo": img_info,
            "prdDescdHtmlInfo": {
                "prdDescdHtmlDescdExplnCntnt": add_lazy_loading(detail_html),
            },
            "attrPrdList": attr_prd_list,
            **({"prdSectList": prd_sect_list} if prd_sect_list else {}),
            # 안전인증 — 의류는 safeCertGbnCd=0 (해당없음)
            "prdSafeCertInfo": gs.get("prdSafeCertInfo")
            or {"safeCertGbnCd": 0, "safeCertOrgCd": 0},
            # 정보고시 — 의류 코드 1001~1009. 수집데이터(소재·색상·제조자·제조국 등) 우선,
            # 없으면 "상품 페이지 참조" 기본값.
            "prdGovPublsItmList": gs.get("prdGovPublsItmList")
            or _build_gov_publs(
                product,
                brand,
                category_prd_cls_cd or str(gs.get("prdClsCd") or ""),
                gov_items,
            ),
        }
    )
    return payload


class GsShopPlugin(MarketPlugin):
    market_type = "gsshop"
    policy_key = "GS샵"
    required_fields = ["name", "sale_price"]

    def _validate_category(self, category_id: str) -> str:
        """GS샵은 B코드(prdClsCd) 또는 숫자(prdSectListSectid) 모두 허용."""
        return category_id or ""

    async def _resolve_category(
        self, session: Any, product: dict[str, Any], category_id: str, account: Any
    ) -> str:
        """매핑이 없으면 소싱 카테고리로 prdClsCd|sectId 자동매칭.
        베이스 handle()의 '카테고리 코드 없음' 검증 전에 호출되어 자동매칭이 통한다.
        """
        return await _resolve_gs_category_id(session, product, category_id)

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        """상품 데이터 → GS샵 API 포맷 변환."""
        gs_margin_rate = kwargs.get("gs_margin_rate", 0)
        sub_sup_cd = kwargs.get("sub_sup_cd", "")
        gs_settings = kwargs.get("gs_settings") or {}
        return _transform_for_gsshop(
            product, category_id, sub_sup_cd, gs_margin_rate, gs_settings
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
        """GS샵 상품 등록 — 전체 로직."""
        from backend.domain.samba.proxy.gsshop import GsShopClient

        # 카테고리 자동결정 — 보통 베이스 handle()의 _resolve_category 훅에서 이미 매칭됨.
        # execute()를 직접 호출하는 경로(테스트 등) 대비 한 번 더 폴백 처리.
        category_id = await _resolve_gs_category_id(session, product, category_id)

        # creds가 비었으면 settings에서 조회.
        # (2026-05-25) store_gsshop 직접 호출 → resolver 위임 + account.tenant_id 자동 추출.
        auth_creds = dict(creds) if creds else {}
        if not auth_creds:
            auth_creds = await _get_setting(session, "gsshop_credentials") or {}
        if not auth_creds or not isinstance(auth_creds, dict):
            from backend.domain.samba.account.resolver import resolve_market_creds

            _tid = getattr(account, "tenant_id", None) if account else None
            auth_creds = (
                await resolve_market_creds(
                    session, _tid, market_type="gsshop", store_key="store_gsshop"
                )
                or {}
            )
        # account의 additional_fields에서 fallback
        if (not auth_creds or not isinstance(auth_creds, dict)) and account:
            extra = getattr(account, "additional_fields", None) or {}
            if (
                extra.get("supCd")
                or extra.get("aesKey")
                or extra.get("apiKeyProd")
                or extra.get("apiKeyDev")
            ):
                auth_creds = extra
        if not auth_creds or not isinstance(auth_creds, dict):
            return {"success": False, "message": "GS샵 설정이 없습니다."}

        sup_cd = (
            auth_creds.get("supCd", "")
            or auth_creds.get("storeId", "")
            or auth_creds.get("vendorId", "")
        )
        # account.seller_id fallback (계정에 supCd가 seller_id로 저장된 경우)
        if not sup_cd and account:
            sup_cd = getattr(account, "seller_id", "") or ""
        aes_key = (
            auth_creds.get("aesKey", "")
            or auth_creds.get("apiKeyProd", "")
            or auth_creds.get("apiKeyDev", "")
        )
        sub_sup_cd = auth_creds.get("subSupCd") or sup_cd
        env = "prod" if auth_creds.get("apiKeyProd") else auth_creds.get("env", "dev")

        # 정책에서 GS샵 마켓마진율 + 기타 등록 설정 조회
        gs_margin_rate = 0
        gs_settings: dict[str, Any] = {}
        policy_id = product.get("applied_policy_id")
        if policy_id:
            from backend.domain.samba.policy.repository import SambaPolicyRepository

            policy_repo = SambaPolicyRepository(session)
            policy = await policy_repo.get_async(policy_id)
            if policy and policy.market_policies:
                gs_policy = policy.market_policies.get("GS샵", {})
                gs_margin_rate = gs_policy.get("gsMarginRate", 0)
                # brandCd, prdClsCd, dlvsCoCd, prdRelspAddrCd 등 등록에 필요한 코드값
                gs_settings = gs_policy.get("gsSettings") or {}
                # 계정별 설정 override — 한 정책에 GS 계정이 여러 개(가디/캐논리츠) 연결된
                # 경우, 등록 대상 계정(account.id) 키의 설정을 공통값 위에 덮어쓴다.
                # → 계정마다 다른 담당MD(operMdId)·출고지(prdRelspAddrCd)·반품지
                #   (prdRetpAddrCd) 등으로 등록됨. 키 없으면 공통 gsSettings 그대로.
                by_acc = gs_policy.get("gsSettingsByAccount") or {}
                _acc_id = str(getattr(account, "id", "") or "") if account else ""
                if _acc_id and isinstance(by_acc.get(_acc_id), dict):
                    gs_settings = {**gs_settings, **by_acc[_acc_id]}
                    # 마켓마진율(공급가 계산용)도 계정별 값이 있으면 우선 적용.
                    # 마놀 25% / 캐논 13% 처럼 계정마다 공급가 마진이 다른 경우 대응.
                    if by_acc[_acc_id].get("gsMarginRate") is not None:
                        gs_margin_rate = by_acc[_acc_id].get("gsMarginRate") or 0

        # 계정 설정 반품/교환비 fallback (정책 gsSettings에 없을 때).
        # returnFee/exchangeFee는 계정 additional_fields에 저장되는데 auth_creds 출처가
        # 설정/resolver일 때 누락될 수 있어, 계정 additional_fields도 함께 조회한다.
        _acct_extra = (
            getattr(account, "additional_fields", None) or {} if account else {}
        )
        if not gs_settings.get("rtpAmt"):
            _rf = auth_creds.get("returnFee") or _acct_extra.get("returnFee")
            if _rf:
                gs_settings = {**gs_settings, "rtpAmt": int(_rf)}
        if not gs_settings.get("exchAmt"):
            _ef = auth_creds.get("exchangeFee") or _acct_extra.get("exchangeFee")
            if _ef:
                gs_settings = {**gs_settings, "exchAmt": int(_ef)}

        client = GsShopClient(sup_cd, aes_key, sub_sup_cd, env)

        # operMdId 미설정 시 MD 목록 API에서 자동 조회
        if not gs_settings.get("operMdId"):
            try:
                md_result = await client.get_md_list()
                md_list = (md_result.get("data", {}) or {}).get("resultList") or []
                if md_list:
                    gs_settings = {
                        **gs_settings,
                        "operMdId": int(md_list[0].get("mdId") or 0),
                    }
            except Exception:
                pass

        # 기존 상품번호(prdCd) 있으면 수정 모드 — 가격+옵션(재고) 업데이트
        if existing_no:
            return await self._update_gsshop(
                client, product, existing_no, gs_margin_rate, gs_settings, sub_sup_cd
            )

        # 분류별 정보고시 그룹 동적 조회 (의류/신발/가방/패션잡화 등 모든 분류 자동)
        gov_items = await _resolve_gov_items(client, category_id, gs_settings)
        goods_data = _transform_for_gsshop(
            product, category_id, sub_sup_cd, gs_margin_rate, gs_settings, gov_items
        )

        # prdSectList 없으면 prdClsCd 이름 기반 전시매장 자동 매핑
        if not goods_data.get("prdSectList"):
            _prd_cls_cd = ""
            _cat = str(category_id or "")
            if "|" in _cat:
                _prd_cls_cd = _cat.split("|", 1)[0].strip()
            elif _cat.upper().startswith("B"):
                _prd_cls_cd = _cat
            if _prd_cls_cd:
                try:
                    _sect_id = await _find_best_sect_id(client, _prd_cls_cd)
                    if _sect_id:
                        goods_data["prdSectList"] = [
                            {
                                "prdSectListSectid": _sect_id,
                                "prdSectListSectGbn": "S",
                                "prdSectListSectStdYn": "Y",
                            }
                        ]
                        logger.info(
                            f"[GS샵] prdSectList 자동매핑: {_prd_cls_cd} → sectId={_sect_id}"
                        )
                except Exception as _e:
                    logger.warning(f"[GS샵] prdSectList 자동매핑 실패(무시): {_e}")

        result = await client.register_goods(goods_data)

        # GS샵 API 응답 검증 — HTTP 200이지만 본문에 fail 포함 가능
        # 응답 구조: result["data"] = raw API JSON, raw["data"] = {"prdCd": "..."}
        raw = result.get("data", {})
        if isinstance(raw, dict):
            if raw.get("result") == "fail" or (
                raw.get("result") and raw.get("result") != "success"
            ):
                msg = raw.get("message", "") or raw.get("code", "") or "등록 실패"
                return {
                    "success": False,
                    "message": f"GS샵 등록 실패: {msg}",
                    "data": raw,
                }

        # prdCd 추출 — {"data": {"data": {"prdCd": "..."}}}
        inner = raw.get("data", {}) if isinstance(raw, dict) else {}
        prd_cd = inner.get("prdCd") if isinstance(inner, dict) else None
        # supPrdCd(=업체상품코드=style_code) 를 product_id로 저장
        # GS API 수정/삭제 endpoint URL이 supPrdCd 기준 (/api/v3/products/{supPrdCd}/price)
        sup_prd_cd_registered = goods_data.get("supPrdCd") or str(prd_cd or "")

        return {
            "success": True,
            "message": "GS샵 등록 성공",
            "product_id": sup_prd_cd_registered,
            "data": result,
        }

    async def _update_gsshop(
        self,
        client: Any,
        product: dict[str, Any],
        prd_cd: str,
        gs_margin_rate: int,
        gs_settings: dict[str, Any],
        sub_sup_cd: str,
    ) -> dict[str, Any]:
        """GS샵 기존 상품 수정 — 가격 + 옵션(재고) 업데이트."""
        from datetime import datetime, timezone, timedelta

        kst = timezone(timedelta(hours=9))
        now_dtm = int(datetime.now(kst).strftime("%Y%m%d%H%M%S"))
        end_dtm = 29991231235959

        sale_price = int(product.get("sale_price") or 0)
        if gs_margin_rate:
            sup_prc = int(sale_price * (100 - gs_margin_rate) / 100 / 10) * 10
        else:
            sup_prc = sale_price

        brand = str(product.get("brand") or "")
        options = product.get("options") or []
        attr_prd_list = _build_attr_prd_list(options, now_dtm, end_dtm, brand)

        errors = []
        _price_md_pending = False

        # 가격 수정
        price_result = await client.update_goods_price(
            prd_cd,
            {
                "prdPrcValidStrDtm": now_dtm,
                "prdPrcValidEndDtm": end_dtm,
                "prdPrcSalePrc": sale_price,
                "prdPrcSupGivRtamt": sup_prc,
                "prdPrcSupGivRtamtCd": "01",
            },
        )
        price_raw = price_result.get("data", {})
        if isinstance(price_raw, dict):
            _pr = price_raw.get("result", "")
            _pm = price_raw.get("message", "")
            if _pr == "fail":
                errors.append(f"가격: {_pm or '실패'}")
            elif _pr == "success":
                # "요청" 포함 = MD승인 대기 (즉시반영 아님)
                # 즉시반영: "P : 처리하였습니다."
                # MD대기: "P : 가격변경 요청되었습니다."
                if "요청" in _pm or "대기" in _pm:
                    _price_md_pending = True
                    logger.info(
                        f"[GS샵] 가격 MD승인 대기: {prd_cd} → {sale_price}원 (승인 후 반영)"
                    )

        # 옵션/재고 수정 (옵션 있을 때만)
        if attr_prd_list:
            attr_result = await client.update_attributes(
                prd_cd,
                attr_prd_list,
                prd_typ_cd=str(gs_settings.get("prdTypCd") or "S"),
                sub_sup_cd=sub_sup_cd,
            )
            attr_raw = attr_result.get("data", {})
            if isinstance(attr_raw, dict) and attr_raw.get("result") == "fail":
                errors.append(f"재고: {attr_raw.get('message', '실패')}")

        if errors:
            return {
                "success": False,
                "message": f"GS샵 수정 실패: {'; '.join(errors)}",
                "product_id": prd_cd,
            }

        if _price_md_pending:
            return {
                "success": True,
                # 롯데홈쇼핑과 동일한 md_pending 규약 — 오토튠 재전송 폭주 방지
                "approval": "md_pending",
                "message": "GS샵 가격 MD승인 대기 (승인 후 반영)",
                "product_id": prd_cd,
            }

        return {
            "success": True,
            "message": "GS샵 수정 성공",
            "product_id": prd_cd,
            "data": price_result,
        }
