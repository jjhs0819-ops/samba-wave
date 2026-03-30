"""롯데ON 마켓 플러그인.

기존 dispatcher._handle_lotteon 로직을 플러그인 구조로 추출.
인증 로드는 base._load_auth 가 처리하므로 execute 에서는 creds dict 사용.
"""

from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.utils.logger import logger

# 브랜드명 접미사 목록 — 검색 전 자동 제거
_BRAND_SUFFIXES = ["키즈", "주니어", "주니어즈", "골프", "Kids", "Junior", "Juniors", "Golf"]

# ──────────────────────────────────────────────────────────────────────────
# scatAttrLst 매핑 테이블
# attr_id: 롯데ON 속성코드 (카테고리 attr_list에서 조회)
# attr_val_id: 롯데ON 속성값코드 (cheetahAttr API에서 확인)
# ──────────────────────────────────────────────────────────────────────────

# 알려진 attr_id → 의미 매핑 (카테고리별로 다를 수 있음)
_ATTR_SEASON_ID = "10378"       # 사용계절
_ATTR_SEX_ID = "11337"          # 성별
_ATTR_PANTS_FIT_ID = "11933"    # 팬츠 핏 (카테고리 BC160501xx)
_ATTR_MATERIAL_ID = "11974"     # 의류 주요소재
_ATTR_COLOR_ID = "12438"        # 통합색상
_ATTR_SIZE_BOTTOM_ID = "12442"  # 성인 하의 사이즈
_ATTR_CLOTHES_TYPE_ID = "776739"  # 의류 종류
_ATTR_ITEM_TYPE_ID = "779690"   # 품목
_ATTR_BOTTOM_LENGTH_ID = "11780"  # 하의기장
_ATTR_LOOK_STYLE_ID = "11809"     # 룩/스타일

# 사용계절 매핑 (무신사 season → attr_val_id)
_SEASON_MAP: dict[str, str] = {
  "사계절": "102421",
  "봄": "102422", "가을": "102422", "spring": "102422", "autumn": "102422", "fall": "102422",
  "여름": "102423", "summer": "102423",
  "겨울": "102424", "winter": "102424",
}

# 성별 매핑 (무신사 sex → attr_val_id)
_SEX_MAP: dict[str, str] = {
  "남성": "109487", "남자": "109487", "male": "109487", "men": "109487", "man": "109487",
  "여성": "109488", "여자": "109488", "female": "109488", "women": "109488", "woman": "109488",
  "공용": "109489", "남녀": "109489", "unisex": "109489",
}

# 의류 주요소재 매핑 (무신사 material 텍스트 키워드 → attr_val_id)
_MATERIAL_MAP: dict[str, str] = {
  "면": "112206", "코튼": "112206", "cotton": "112206",
  "폴리에스터": "716573347", "폴리에스텔": "716573347", "polyester": "716573347", "폴리": "716573347",
  "기모": "632861291",
  "나일론": "112203", "nylon": "112203",
  "리넨": "112204", "linen": "112204",
  "실크": "112205", "silk": "112205",
  "레이온": "718490456", "rayon": "718490456",
  "모달": "876098952", "modal": "876098952",
  "아크릴": "733156070", "acrylic": "733156070",
  "데님": "112190", "청": "112190", "denim": "112190",
  "벨벳": "112196", "velvet": "112196",
  "모": "112208", "울": "112208", "wool": "112208",
  "캐시미어": "591014974", "cashmere": "591014974",
  "코듀로이": "632861290", "corduroy": "632861290",
  "플리스": "876098953", "fleece": "876098953",
  "가죽": "547696592", "leather": "547696592",
  "인조가죽": "788761126",
  "폴리우레탄": "752495629",
  "새틴": "876098955", "satin": "876098955",
  "트위드": "835835046", "tweed": "835835046",
  "텐셀": "112207", "tencel": "112207",
  "퍼": "547696582", "fur": "547696582",
  "앙고라": "636940692", "angora": "636940692",
}

# 통합색상 매핑 (무신사 color 텍스트 키워드 → attr_val_id)
_COLOR_MAP: dict[str, str] = {
  "블랙": "114835", "검정": "114835", "black": "114835",
  "화이트": "114794", "흰": "114794", "white": "114794",
  "네이비": "114833", "navy": "114833",
  "그레이": "114830", "회색": "114830", "gray": "114830", "grey": "114830", "그레": "114830",
  "베이지": "114772", "beige": "114772",
  "브라운": "114782", "갈색": "114782", "brown": "114782",
  "카키": "114816", "khaki": "114816",
  "레드": "114822", "빨강": "114822", "red": "114822",
  "블루": "114804", "파랑": "114804", "blue": "114804",
  "그린": "114811", "초록": "114811", "green": "114811",
  "핑크": "114796", "분홍": "114796", "pink": "114796",
  "옐로우": "114836", "노랑": "114836", "yellow": "114836",
  "오렌지": "114818", "orange": "114818",
  "퍼플": "91478236", "보라": "91478236", "purple": "91478236",
  "아이보리": "114773", "ivory": "114773",
  "차콜": "114831", "charcoal": "114831",
  "올리브": "114814", "olive": "114814",
  "와인": "114823", "wine": "114823",
  "버건디": "114824", "burgundy": "114824",
  "멀티": "114839", "multi": "114839",
  "코랄": "114820", "coral": "114820",
  "스카이": "114806", "sky": "114806",
  "라벤다": "114802", "lavender": "114802",
  "민트": "114812", "mint": "114812",
  "머스타드": "114837", "mustard": "114837",
  "골드": "114778", "gold": "114778",
  "실버": "114828", "silver": "114828",
  "연두": "114813",
  "데님": "114810",
  "아쿠아": "114807", "aqua": "114807",
}

# 의류 종류 매핑 (category 텍스트 키워드 → attr_val_id)
_CLOTHES_TYPE_MAP: dict[str, str] = {
  "바지": "625980564", "팬츠": "625980564", "레깅스": "625980564",
  "자켓": "625980557", "코트": "625980557",
  "점퍼": "625980558", "패딩": "625980558", "야상": "625980558",
  "가디건": "625980559",
  "니트": "625980561", "조끼": "625980561",
  "셔츠": "625980562", "블라우스": "625980562",
  "티셔츠": "625980563", "맨투맨": "625980563", "후디": "625980563", "후드": "625980563",
  "스커트": "625980566",
  "원피스": "625980567", "점프수트": "625980567",
  "수영복": "628783835", "래시가드": "628783835",
  "정장": "628785579",
  "트레이닝": "628785581",
}

# 성인 하의 사이즈 매핑 (옵션명 → attr_val_id)
_SIZE_BOTTOM_MAP: dict[str, str] = {
  "XS": "114990", "S": "114991", "M": "114992", "L": "114993",
  "XL": "114994", "2XL": "114995", "XXL": "114995", "3XL": "114996",
  "4XL": "114997", "5XL": "114998",
  "22": "803338603", "23": "114969", "24": "114970", "25": "114971",
  "26": "114972", "27": "114973", "28": "114974", "29": "114975",
  "30": "114976", "31": "114977", "32": "114978", "33": "114979",
  "34": "114980", "35": "114981", "36": "114982", "38": "114984",
  "40": "114986", "42": "91478294", "44": "91478295",
  "FREE": "114968", "free": "114968", "one size": "114968", "1size": "114968", "프리": "114968",
}

# 팬츠 핏 매핑 (상품명/태그 키워드 → attr_val_id)
_PANTS_FIT_MAP: dict[str, str] = {
  "배기": "112026", "baggy": "112026",
  "부츠컷": "112027", "boot": "112027",
  "와이드": "112028", "wide": "112028",
  "스트레이트": "112029", "일자": "112029", "straight": "112029",
  "슬림": "112030", "스키니": "112030", "slim": "112030", "skinny": "112030",
  "테이퍼드": "547916208", "tapered": "547916208",
  "조거": "610443195", "jogger": "610443195",
  "핀턱": "773234579", "pintuck": "773234579",
}

# 하의기장 매핑 (상품명/카테고리 키워드 → attr_val_id, 기본: 긴바지)
_BOTTOM_LENGTH_MAP: dict[str, str] = {
  "반바지": "111194", "숏": "111194", "short": "111194",
  "숏팬츠": "558495938", "3부": "558495938",
  "7부": "111198",
  "9부": "111200",
}

# 룩/스타일 매핑 (브랜드/상품명 키워드 → attr_val_id, 기본: 캐주얼)
_LOOK_STYLE_MAP: dict[str, str] = {
  # 스포츠/아웃도어 브랜드 → 아웃도어
  "아디다스": "547698710", "나이키": "547698710", "퓨마": "547698710",
  "리복": "547698710", "뉴발란스": "547698710", "언더아머": "547698710",
  "컬럼비아": "547698710", "노스페이스": "547698710", "파타고니아": "547698710",
  "살로몬": "547698710", "아식스": "547698710", "스포츠": "547698710",
  "아웃도어": "547698710", "sport": "547698710", "outdoor": "547698710",
  # 힙합/스트릿
  "스트릿": "111345", "힙합": "111345", "street": "111345",
  # 빈티지/히피
  "빈티지": "111344", "vintage": "111344", "히피": "111344",
  # 레트로
  "레트로": "547919177", "retro": "547919177",
  # 밀리터리
  "밀리터리": "629485501", "military": "629485501",
}

# optValCd → 롯데ON 표시명 (scatAttrLst의 optVal 필드 — 필수, null 불가)
_OPT_VAL_LABELS: dict[str, str] = {
  # 사용계절
  "102421": "사계절용", "102422": "봄/가을용", "102423": "여름용", "102424": "겨울용",
  # 성별
  "109487": "남성", "109488": "여성", "109489": "공용",
  # 의류 주요소재
  "112206": "면", "716573347": "폴리에스테르", "632861291": "기모",
  "112203": "나일론", "112204": "리넨", "112205": "실크",
  "718490456": "레이온", "876098952": "모달", "733156070": "아크릴",
  "112190": "데님", "112196": "벨벳", "112208": "모",
  "591014974": "캐시미어", "632861290": "코듀로이", "876098953": "플리스",
  "547696592": "가죽", "788761126": "인조가죽", "752495629": "폴리우레탄",
  "876098955": "새틴", "835835046": "트위드", "112207": "텐셀",
  "547696582": "퍼(FUR)", "636940692": "앙고라",
  # 통합색상
  "114835": "블랙", "114794": "화이트", "114833": "네이비",
  "114830": "그레이", "114772": "베이지", "114782": "브라운",
  "114816": "카키", "114822": "레드", "114804": "블루",
  "114811": "그린", "114796": "핑크", "114836": "옐로우",
  "114818": "오렌지", "91478236": "퍼플", "114773": "아이보리",
  "114831": "차콜", "114814": "올리브", "114823": "와인",
  "114824": "버건디", "114839": "멀티", "114820": "코랄",
  "114806": "스카이블루", "114802": "라벤더", "114812": "민트",
  "114837": "머스타드", "114778": "골드", "114828": "실버",
  "114813": "연두", "114810": "데님", "114807": "아쿠아",
  # 의류 종류
  "625980564": "바지/레깅스", "625980557": "자켓/코트",
  "625980558": "점퍼/패딩", "625980559": "가디건",
  "625980561": "니트/조끼", "625980562": "셔츠/블라우스",
  "625980563": "티셔츠/맨투맨/후드", "625980566": "스커트",
  "625980567": "원피스/점프수트", "628783835": "수영복/래시가드",
  "628785579": "정장", "628785581": "트레이닝",
  # 품목 (779690) — 카테고리별 단일값
  "628662010": "의류",
  # 하의기장
  "111194": "반바지", "558495938": "숏팬츠/3부", "111198": "7부", "111200": "9부", "111202": "긴바지",
  # 룩/스타일
  "111334": "캐주얼", "111338": "오피스", "111340": "글램/섹시", "111342": "펑크",
  "111344": "빈티지/히피", "111345": "힙합/스트릿", "111346": "페미닌",
  "547698709": "마린", "547698710": "아웃도어", "547698711": "파티",
  "547698712": "프레피", "547698713": "리조트", "547698714": "웨딩",
  "547698715": "컨트리", "547919177": "레트로", "604509736": "로맨틱",
  "604509737": "큐트", "629429090": "에스닉", "629485501": "밀리터리",
  # 성인 하의 사이즈
  "114968": "FREE", "114990": "XS", "114991": "S",
  "114992": "M", "114993": "L", "114994": "XL",
  "114995": "2XL", "114996": "3XL", "114997": "4XL", "114998": "5XL",
  "803338603": "22", "114969": "23", "114970": "24", "114971": "25",
  "114972": "26", "114973": "27", "114974": "28", "114975": "29",
  "114976": "30", "114977": "31", "114978": "32", "114979": "33",
  "114980": "34", "114981": "35", "114982": "36", "114984": "38",
  "114986": "40", "91478294": "42", "91478295": "44",
  # 팬츠 핏
  "112026": "배기", "112027": "부츠컷", "112028": "와이드",
  "112029": "스트레이트", "112030": "슬림", "547916208": "테이퍼드",
  "610443195": "조거", "773234579": "핀턱",
}


def _is_bottom_product(product: dict[str, Any]) -> bool:
  """상품이 하의(바지/스커트류)인지 판별."""
  BOTTOM_KW = {
    "바지", "팬츠", "청바지", "레깅스", "스커트", "치마", "반바지", "쇼츠",
    "shorts", "pants", "skirt", "leggings", "trousers",
  }
  text = " ".join(filter(None, [
    product.get("name", ""),
    product.get("category2", ""),
    product.get("category3", ""),
    product.get("category4", ""),
  ])).lower()
  return any(kw in text for kw in BOTTOM_KW)


def _build_scat_attr_lst(product: dict[str, Any], attr_ids: list[str]) -> list[dict[str, str]]:
  """무신사 소싱 데이터 → 롯데ON scatAttrLst 변환.

  Args:
    product: CollectedProduct dict (product_copy)
    attr_ids: 카테고리에서 지원하는 attr_id 목록

  Returns:
    [{"optCd": attr_id, "optValCd": attr_val_id}, ...]
  """
  result: list[dict[str, str]] = []
  attr_id_set = set(attr_ids)
  is_bottom = _is_bottom_product(product)

  def _add(attr_id: str, val_id: str) -> None:
    if not (attr_id in attr_id_set and val_id):
      return
    opt_val = _OPT_VAL_LABELS.get(val_id, "")
    if not opt_val:
      logger.warning(f"[롯데ON] optVal 라벨 없음 — optCd={attr_id} optValCd={val_id} (속성 제외)")
      return
    result.append({"optCd": attr_id, "optValCd": val_id, "optVal": opt_val})

  def _keyword_match(text: str, mapping: dict[str, str]) -> str:
    """텍스트에서 첫 번째 매칭 키워드의 attr_val_id 반환."""
    text_lower = text.lower()
    for key, val in mapping.items():
      if key.lower() in text_lower:
        return val
    return ""

  # ── 사용계절 ──────────────────────────────────────────────────────
  # "2026 SS", "FW", "AW" 등 패션 시즌 코드 지원
  season_raw = product.get("season") or []
  if isinstance(season_raw, str):
    season_raw = [s.strip() for s in season_raw.replace(",", "/").split("/") if s.strip()]
  if season_raw:
    combined = " ".join(season_raw).lower()
    season_set = {s for s in season_raw if s in {"봄", "여름", "가을", "겨울"}}
    if len(season_set) >= 3 or "사계절" in combined:
      _add(_ATTR_SEASON_ID, "102421")  # 사계절용
    elif re.search(r'\b(fw|aw|fall|autumn|winter|겨울)\b', combined):
      _add(_ATTR_SEASON_ID, "102424")  # 겨울용 (FW/AW)
    elif re.search(r'\b(ss|spring|봄|가을)\b', combined):
      _add(_ATTR_SEASON_ID, "102422")  # 봄/가을용 (SS)
    elif re.search(r'\b(summer|여름)\b', combined):
      _add(_ATTR_SEASON_ID, "102423")  # 여름용
  # 사용계절 매핑 없으면 사계절용 기본값
  if _ATTR_SEASON_ID in attr_id_set and not any(r.get("optCd") == _ATTR_SEASON_ID for r in result):
    _add(_ATTR_SEASON_ID, "102421")

  # ── 성별 ─────────────────────────────────────────────────────────
  sex = (product.get("sex") or "").lower()
  val = _keyword_match(sex, _SEX_MAP)
  if val:
    _add(_ATTR_SEX_ID, val)

  # ── 의류 주요소재 ─────────────────────────────────────────────────
  material = (product.get("material") or "").lower()
  val = _keyword_match(material, _MATERIAL_MAP)
  if val:
    _add(_ATTR_MATERIAL_ID, val)

  # ── 통합색상 ─────────────────────────────────────────────────────
  color = (product.get("color") or "").lower()
  val = _keyword_match(color, _COLOR_MAP)
  if val:
    _add(_ATTR_COLOR_ID, val)

  # ── 의류 종류 (category1~4 텍스트에서 추출) ──────────────────────
  cat_text = " ".join(filter(None, [
    product.get("category1") or "",
    product.get("category2") or "",
    product.get("category3") or "",
    product.get("category4") or "",
  ]))
  val = _keyword_match(cat_text, _CLOTHES_TYPE_MAP)
  if val:
    _add(_ATTR_CLOTHES_TYPE_ID, val)

  # ── 품목 → 고정값 의류 ────────────────────────────────────────────
  _add(_ATTR_ITEM_TYPE_ID, "628662010")

  # ── 성인 하의 사이즈 (하의 상품만, options 에서 추출) ──────────
  if is_bottom and _ATTR_SIZE_BOTTOM_ID in attr_id_set:
    options = product.get("options") or []
    added_sizes: set[str] = set()
    for opt in options:
      size_nm = (opt.get("name") or opt.get("size") or "").strip()
      val = _SIZE_BOTTOM_MAP.get(size_nm, "")
      if val and val not in added_sizes:
        opt_val_nm = _OPT_VAL_LABELS.get(val, "")
        if opt_val_nm:
          result.append({"optCd": _ATTR_SIZE_BOTTOM_ID, "optValCd": val, "optVal": opt_val_nm})
          added_sizes.add(val)

  # ── 팬츠 핏 (하의 상품만, 상품명 + 태그에서 키워드 추출) ────────
  if is_bottom and _ATTR_PANTS_FIT_ID in attr_id_set:
    name_and_tags = (product.get("name") or "") + " " + " ".join(product.get("tags") or [])
    val = _keyword_match(name_and_tags, _PANTS_FIT_MAP)
    if val:
      _add(_ATTR_PANTS_FIT_ID, val)

  # ── 하의기장 (하의 상품만, 기본: 긴바지) ──────────────────────
  if is_bottom and _ATTR_BOTTOM_LENGTH_ID in attr_id_set:
    search_text = (product.get("name") or "") + " " + cat_text
    val = _keyword_match(search_text, _BOTTOM_LENGTH_MAP)
    _add(_ATTR_BOTTOM_LENGTH_ID, val or "111202")  # 키워드 없으면 긴바지

  # ── 룩/스타일 (항상 캐주얼 고정) ───────────────────────────────
  if _ATTR_LOOK_STYLE_ID in attr_id_set:
    _add(_ATTR_LOOK_STYLE_ID, "111334")

  return result


def _strip_brand_suffix(name: str) -> str:
  """브랜드명 뒤에 붙은 접미사 제거. 예: '나이키 키즈' → '나이키'"""
  for suffix in _BRAND_SUFFIXES:
    if name.endswith(" " + suffix):
      return name[:-(len(suffix) + 1)].strip()
  return name


async def _search_brand_no(client: Any, brand_name: str) -> str:
  """접미사 제거 → 첫 단어만 → 스킵 순서로 브랜드 검색. brdNo 반환."""
  stripped = _strip_brand_suffix(brand_name)
  candidates = [stripped]

  # 첫 단어만 시도 (접미사 제거 결과와 다를 때만)
  first_word = stripped.split()[0] if stripped else ""
  if first_word and first_word != stripped:
    candidates.append(first_word)

  for candidate in candidates:
    try:
      result = await client.search_brand(candidate)
      items = result.get("itemList") or result.get("data") or []
      if isinstance(items, list) and items:
        item = items[0]
        d = item.get("data", item) if isinstance(item, dict) else item
        # 브랜드 검색 응답(cheetahBrnd)의 실제 키: brnd_id
        brd_no = d.get("brnd_id", "") or d.get("brnd_no", "") or d.get("brdNo", "")
        if brd_no:
          logger.info(f"[롯데ON] 브랜드 검색 성공: {brand_name!r} → {candidate!r} brdNo={brd_no}")
          return str(brd_no)
    except Exception as e:
      logger.warning(f"[롯데ON] 브랜드 검색 실패 ({candidate!r}): {e}")

  logger.info(f"[롯데ON] 브랜드 검색 스킵 — 브랜드 공란으로 등록 진행: {brand_name!r}")
  return ""


class LotteonPlugin(MarketPlugin):
  market_type = "lotteon"
  policy_key = "롯데ON"
  required_fields = ["name", "sale_price"]

  def _validate_category(self, category_id: str) -> str:
    """롯데ON은 BC 접두사 카테고리 코드 허용 (BC41030100 형식)."""
    return category_id or ""

  def transform(self, product: dict, category_id: str, **kwargs) -> dict:
    """상품 데이터 → 롯데ON API 포맷 변환."""
    from backend.domain.samba.proxy.lotteon import LotteonClient
    tr_grp_cd = kwargs.get("tr_grp_cd", "SR")
    tr_no = kwargs.get("tr_no", "")
    return LotteonClient.transform_product(product, category_id, tr_grp_cd, tr_no)

  async def execute(
    self,
    session,
    product: dict,
    creds: dict,
    category_id: str,
    account,
    existing_no: str,
  ) -> dict[str, Any]:
    """롯데ON 상품 등록/수정 — 전체 로직."""
    from backend.domain.samba.proxy.lotteon import LotteonClient

    api_key = creds.get("apiKey", "")

    # account 필드에서 보완
    if not api_key and account:
      extras = getattr(account, "additional_fields", None) or {}
      api_key = extras.get("apiKey", "") or getattr(account, "api_key", "") or ""

    if not api_key:
      return {
        "success": False,
        "message": "롯데ON API Key가 비어있습니다. 설정에서 해당 계정을 수정 후 저장해주세요.",
      }

    # ── 성별 오버라이드: sex == "여성"이면 남성→여성 카테고리 경로 변환 ──
    # 카테고리가 경로 문자열일 때만 적용 (BC코드 변환 전에 처리)
    if (product.get("sex") or "").strip() == "여성" and category_id and ">" in category_id:
      from backend.domain.samba.category.service import _LOTTEON_M_TO_F
      female_cat = _LOTTEON_M_TO_F.get(category_id)
      if female_cat:
        logger.info(f"[롯데ON] 성별 오버라이드: {category_id!r} → {female_cat!r}")
        category_id = female_cat

    # ── 소싱된 롯데ON 상품: _lotteonScatNo 원본 BC코드 직접 사용 ──────────
    # 롯데ON 소싱 상품은 수집 시점의 정확한 BC코드가 저장되어 있으므로
    # fuzzy match 없이 직접 사용 (오매핑 방지)
    _scat_no = str(product.get("_lotteonScatNo", "") or "").strip()
    if _scat_no and _scat_no.startswith("BC") and category_id and ">" in category_id:
      logger.info(f"[롯데ON] 소싱 원본 BC코드 사용 (fuzzy match 스킵): {_scat_no}")
      category_id = _scat_no

    # category_id가 경로 문자열(">" 포함)이면 DB 코드맵에서 변환 시도
    if category_id and ">" in category_id:
      from backend.domain.samba.category.repository import (
        SambaCategoryMappingRepository,
        SambaCategoryTreeRepository,
      )
      from backend.domain.samba.category.service import SambaCategoryService
      _cat_svc = SambaCategoryService(
        SambaCategoryMappingRepository(session),
        SambaCategoryTreeRepository(session),
      )
      resolved = await _cat_svc.resolve_category_code("lotteon", category_id)
      if resolved:
        logger.info(f"[롯데ON] 카테고리 코드 변환: '{category_id}' → {resolved}")
        category_id = resolved
      else:
        return {
          "success": False,
          "message": (
            f"롯데ON 카테고리 코드를 찾을 수 없습니다. "
            f"카테고리 설정에서 '롯데ON 동기화'를 실행한 뒤 "
            f"AI 자동 매핑을 다시 실행해주세요. "
            f"(현재 값: {category_id})"
          ),
        }

    client = LotteonClient(api_key)
    # 거래처 정보 자동 획득 (trGrpCd, trNo)
    await client.test_auth()

    product_copy = dict(product)

    # ── 1. 계정 additional_fields 주입 ──────────────────────────────
    extras: dict[str, Any] = {}
    if account:
      extras = getattr(account, "additional_fields", None) or {}

    # Settings 폴백 (계정에 출고지/배송비정책/회수지 없을 때)
    if not extras.get("owhpNo"):
      from backend.domain.samba.forbidden.model import SambaSettings
      from sqlmodel import select
      stmt = select(SambaSettings).where(SambaSettings.key == "store_lotteon")
      result = await session.execute(stmt)
      row = result.scalars().first()
      if row and isinstance(row.value, dict):
        extras = {**row.value, **extras}

    product_copy["owhp_no"] = extras.get("owhpNo", "")
    product_copy["dv_cst_pol_no"] = extras.get("dvCstPolNo", "")
    product_copy["island_dv_cst_pol_no"] = extras.get("dvIslandCstPolNo", "")
    product_copy["rtrp_no"] = extras.get("rtrpNo", "")
    product_copy["cmbn_dv_psb_yn"] = extras.get("bundleDelivery", "Y")
    # 계정 추가 설정 주입
    if extras.get("asPhone"):
      # 설정의 A/S 전화번호를 그대로 사용 (브랜드명 불포함 — 다브랜드 운영)
      product_copy["_as_phone"] = extras["asPhone"]
    if extras.get("asMessage"):
      product_copy["_as_message"] = extras["asMessage"]
    if extras.get("discountRate"):
      product_copy["_discount_rate"] = int(extras["discountRate"])
    if extras.get("returnFee"):
      product_copy["_return_fee"] = int(extras["returnFee"])
    if extras.get("exchangeFee"):
      product_copy["_exchange_fee"] = int(extras["exchangeFee"])
    if extras.get("jejuFee"):
      product_copy["_jeju_fee"] = int(extras["jejuFee"])
    if extras.get("stockQuantity"):
      product_copy["_stock_quantity"] = int(extras["stockQuantity"])

    # ── 2. 정책 설정 주입 ────────────────────────────────────────────
    policy_id = product.get("applied_policy_id")
    if policy_id:
      from backend.domain.samba.policy.repository import SambaPolicyRepository
      policy_repo = SambaPolicyRepository(session)
      _policy = await policy_repo.get_async(policy_id)
      if _policy:
        mp = (_policy.market_policies or {}).get("롯데ON", {})
        pr = (_policy.pricing or {})
        # 배송비
        shipping = int(mp.get("shippingCost") or pr.get("shippingCost") or 0)
        if shipping > 0:
          product_copy["_delivery_fee_type"] = "PAID"
          product_copy["_delivery_base_fee"] = shipping
        # 최대 재고
        if mp.get("maxStock"):
          product_copy["_max_stock"] = int(mp["maxStock"])

    # ── 3. 브랜드 검색 (접미사 제거 → 첫 단어 → 스킵 폴백) ──────────
    brand_name = product_copy.get("brand", "")
    if brand_name and not product_copy.get("brand_no"):
      brd_no = await _search_brand_no(client, brand_name)
      if brd_no:
        product_copy["brand_no"] = brd_no

    # ── 비리프 카테고리 자동 보정 (leaf_yn="Y" 될 때까지 최대 4단계 반복 탐색) ──
    if category_id and category_id.endswith("0000"):
      logger.info(f"[롯데ON] 비리프 카테고리 감지 — 하위 탐색 시작: {category_id}")
      for _step in range(4):
        try:
          child_result = await client.get_categories(parent_id=category_id)
          child_items = child_result.get("itemList") or []
          logger.info(f"[롯데ON] 하위 카테고리 조회 결과: {len(child_items)}개 (step={_step+1})")
          if not child_items:
            logger.warning(f"[롯데ON] 비리프 보정 중단 — 하위 없음 (parent={category_id})")
            break
          d = child_items[0].get("data", child_items[0])
          child_id = d.get("std_cat_id", "") or d.get("cat_id", "") or d.get("id", "")
          leaf_yn = d.get("leaf_yn", "")
          if not child_id:
            logger.warning(f"[롯데ON] 비리프 보정 중단 — std_cat_id 없음. 키: {list(d.keys())[:10]}")
            break
          logger.info(f"[롯데ON] 비리프 자동 보정: {category_id} → {child_id} (leaf_yn={leaf_yn})")
          category_id = child_id
          if leaf_yn == "Y":
            break  # 최하위 도달
          # leaf_yn이 "N"이거나 불분명하면 한 번 더 탐색
        except Exception as e:
          logger.warning(f"[롯데ON] 하위 카테고리 조회 실패 (무시): {e}")
          break

    # 전시카테고리(FC...) + attr_list 자동 조회 (1번 API 호출로 통합)
    disp_cat_id = ""
    category_attr_ids: list[str] = []
    try:
      cat_result = await client.get_categories(cat_id=category_id)
      items = cat_result.get("itemList") or []
      if items:
        d = items[0].get("data", {})
        disp_list = d.get("disp_list", [])
        if disp_list:
          disp_cat_id = disp_list[0].get("disp_cat_id", "")
        # 속성 attr_id + attr_nm 목록 추출 (scatAttrLst 생성용)
        _attr_raw = d.get("attr_list") or []
        category_attr_ids = [str(a.get("attr_id", "")) for a in _attr_raw if a.get("attr_id")]
        logger.debug(
          f"[롯데ON] attr_list 상세: "
          f"{[(str(a.get('attr_id','')), a.get('attr_nm','')) for a in _attr_raw]}"
        )
      logger.info(f"[롯데ON] 전시카테고리 조회: {category_id} → {disp_cat_id}, attr_ids={len(category_attr_ids)}개")
    except Exception as e:
      logger.warning(f"[롯데ON] 전시카테고리 조회 실패 (무시): {e}")

    # 속성정보(scatAttrLst) 생성 — 무신사 소싱 데이터 → 롯데ON 속성값 매핑
    if category_attr_ids:
      # 소스 필드 디버그 (성별/계절 오매핑 원인 파악용)
      logger.info(
        f"[롯데ON][속성소스] sex={product_copy.get('sex')!r} "
        f"season={product_copy.get('season')!r} "
        f"material={product_copy.get('material')!r} "
        f"color={product_copy.get('color')!r} "
        f"category1={product_copy.get('category1')!r} "
        f"name={product_copy.get('name', '')[:40]!r}"
      )
      scat_attr_lst = _build_scat_attr_lst(product_copy, category_attr_ids)
      product_copy["_scat_attr_lst"] = scat_attr_lst
      logger.info(f"[롯데ON] scatAttrLst 생성: {len(scat_attr_lst)}개 — {[a['optVal'] for a in scat_attr_lst]}")

    data = LotteonClient.transform_product(
      product_copy, category_id, client.tr_grp_cd or "SR", client.tr_no, disp_cat_id
    )

    # ── 4. 등록 / 수정 ───────────────────────────────────────────────
    try:
      if existing_no:
        # ── 기존 단품 eitmNo 조회 (수정 시 중복 방지) ───────────────
        existing_eitm_nos: list[str] = []
        existing_sitm_nos: list[str] = []  # 통합EC판매자단품번호 — 살수록할인 API에서 사용
        try:
          prod_resp = await client.get_product(existing_no)
          inner = prod_resp.get("data", prod_resp)
          if isinstance(inner, dict):
            spd_info = inner.get("spdLst") or inner.get("spdInfo") or inner
            if isinstance(spd_info, list) and spd_info:
              spd_info = spd_info[0]
            if isinstance(spd_info, dict):
              itm_lst_raw = spd_info.get("itmLst") or []
              existing_eitm_nos = [
                str(itm.get("eitmNo")) for itm in itm_lst_raw if itm.get("eitmNo")
              ]
              # sitmNo = 롯데ON 내부 단품번호 (예: LO2643843825_2643843826)
              existing_sitm_nos = [
                str(itm.get("sitmNo")) for itm in itm_lst_raw if itm.get("sitmNo")
              ]
          logger.info(f"[롯데ON] 기존 단품 eitmNo: {existing_eitm_nos}, sitmNo: {existing_sitm_nos}")
        except Exception as e:
          logger.warning(f"[롯데ON] 기존 단품 조회 실패 (무시): {e}")

        # spdNo + selPrdNo 모두 주입 (롯데ON 수정 API 필수값)
        if data.get("spdLst") and isinstance(data["spdLst"], list):
          data["spdLst"][0]["spdNo"] = existing_no
          data["spdLst"][0]["selPrdNo"] = existing_no
          # 수정 API는 itmLst를 "새 단품 추가"로 처리 → 기존 옵션과 중복 에러 발생
          # 상품 헤더(이름/이미지/카테고리/가격)만 업데이트하고 itmLst는 제거
          data["spdLst"][0].pop("itmLst", None)
          data["spdLst"][0].pop("sitmYn", None)
        logger.info(f"[롯데ON] 수정 모드 — 기존 spdNo={existing_no!r}")
        result = await client.update_product(data)
        # 수정 API가 새 spdNo를 반환하는 경우 (수정본 별도 상품번호 발급)
        new_spd_no = result.get("spdNo", "") or ""
        effective_no = new_spd_no if new_spd_no and new_spd_no != existing_no else existing_no
        if new_spd_no and new_spd_no != existing_no:
          logger.info(f"[롯데ON] 수정 후 새 spdNo 발급: {existing_no} → {new_spd_no}")
        # ── 수정 후 프로모션 재설정 ──────────────────────────────
        await self._apply_promotions(client, effective_no, extras, is_update=True, eitm_nos=existing_sitm_nos)
        # ── 홍보문구 갱신 (180일 자동 연장) ────────────────────
        publicity_phrase = extras.get("publicityPhrase", "").strip()
        if publicity_phrase:
          try:
            await client.register_publicity_sentence(effective_no, publicity_phrase)
          except Exception as e:
            logger.warning(f"[롯데ON] 홍보문구 갱신 실패 (무시): {e}")
        ret: dict[str, Any] = {"success": True, "message": "롯데ON 수정 성공", "data": result}
        if effective_no != existing_no:
          # service.py가 market_product_nos를 새 번호로 갱신하도록 반환
          ret["spdNo"] = effective_no
        return ret
      else:
        result = await client.register_product(data)
        # proxy.register_product 가 spdNo를 최상위로 반환 (service.py가 result.get("spdNo")로 읽음)
        spd_no = result.get("spdNo", "") or result.get("epdNo", "")
        logger.info(f"[롯데ON] 등록 완료 — spdNo={spd_no!r}")

        # ── 등록 후 프로모션 설정: sitmNo 조회 후 전달 ────────────
        if spd_no:
          # 롯데ON 상품 처리 대기 — 즉시 호출 시 9000/9999 에러 발생
          import asyncio
          await asyncio.sleep(5)
          new_sitm_nos: list[str] = []
          try:
            prod_resp = await client.get_product(spd_no)
            inner = prod_resp.get("data", prod_resp)
            if isinstance(inner, dict):
              spd_info = inner.get("spdLst") or inner.get("spdInfo") or inner
              if isinstance(spd_info, list) and spd_info:
                spd_info = spd_info[0]
              if isinstance(spd_info, dict):
                new_sitm_nos = [
                  str(itm.get("sitmNo")) for itm in (spd_info.get("itmLst") or []) if itm.get("sitmNo")
                ]
          except Exception as e:
            logger.warning(f"[롯데ON] 신규 단품 sitmNo 조회 실패 (무시): {e}")
          await self._apply_promotions(client, spd_no, extras, is_update=False, eitm_nos=new_sitm_nos)

        # ── 홍보문구 등록 ────────────────────────────────────────────
        if spd_no:
          publicity_phrase = extras.get("publicityPhrase", "").strip()
          if publicity_phrase:
            logger.info(f"[롯데ON] 홍보문구 등록 시도 — spdNo={spd_no!r} phrase={publicity_phrase!r}")
            try:
              await client.register_publicity_sentence(spd_no, publicity_phrase)
            except Exception as e:
              logger.warning(f"[롯데ON] 홍보문구 등록 실패 (무시): {e}")
          else:
            logger.debug(f"[롯데ON] 홍보문구 미설정 (설정 > 롯데ON > 상품 홍보문구 입력 필요)")

        return {"success": True, "message": "롯데ON 등록 성공", "data": result, "spdNo": spd_no}
    except Exception as e:
      action = "수정" if existing_no else "등록"
      logger.error(f"[롯데ON] {action} 실패: {e}")
      return {"success": False, "message": f"롯데ON {action} 실패: {e}"}

  async def _apply_promotions(self, client: Any, spd_no: str, extras: dict, is_update: bool = False, eitm_nos: list[str] | None = None) -> None:
    """등록/수정 후 프로모션 설정 — 실패해도 결과에 영향 없음."""

    # ── 즉시할인 ───────────────────────────────────────────────────
    discount_rate = int(extras.get("discountRate") or 0)
    if discount_rate > 0:
      try:
        resp = await client.save_immediate_discount(spd_no, discount_rate, is_update=is_update)
        logger.info(f"[롯데ON] 즉시할인 설정 완료: {discount_rate}% → {resp}")
      except Exception as e:
        logger.warning(f"[롯데ON] 즉시할인 설정 실패 (무시): {e}")

    # ── 행사 제외 설정 ──────────────────────────────────────────────
    # additional_fields 키: ownerDiscountExclude, unitCouponExclude,
    #   deliveryCouponExclude, cmPcsExclude, pcsExclude (Y/N)
    exception_flags: dict[str, str] = {}
    _flag_map = {
      "ownerDiscountExclude": "ownrDscExYn",
      "unitCouponExclude": "pdUtCpnExYn",
      "deliveryCouponExclude": "dvCpnExYn",
      "cmPcsExclude": "cmPcsDscExYn",
      "pcsExclude": "pcsDscExYn",
    }
    for settings_key, api_key in _flag_map.items():
      val = extras.get(settings_key, "")
      if val in ("Y", "N"):
        exception_flags[api_key] = val

    if exception_flags:
      try:
        resp = await client.save_product_exception(spd_no, exception_flags)
        logger.info(f"[롯데ON] 행사제외 설정 완료: {exception_flags} → {resp}")
      except Exception as e:
        logger.warning(f"[롯데ON] 행사제외 설정 실패 (무시): {e}")

    # ── L.POINT 추가적립 ────────────────────────────────────────────
    # purchasePointRate > 0 이면 자동 활성화 (체크박스 제거됨)
    lpoint_from_ui = int(extras.get("purchasePointRate") or 0)
    lpoint_accm = int(extras.get("lpointAccm") or 0) or lpoint_from_ui
    if lpoint_accm > 0:
      try:
        accm_days = str(extras.get("lpointAccmDays") or "7")
        # 리뷰/사진 포인트: lpointReview/Photo 직접값 우선, UI 필드(reviewTextPoint/reviewPhotoPoint) 폴백
        lpoint_review = int(extras.get("lpointReview") or extras.get("reviewTextPoint") or 0)
        lpoint_photo = int(extras.get("lpointPhoto") or extras.get("reviewPhotoPoint") or 0)
        lpoint_video = int(extras.get("lpointVideo") or extras.get("reviewVideoPoint") or 0)
        resp = await client.save_lpoint_accumulation(
          spd_no,
          accm_val1=lpoint_accm,
          accm_vp_knd_cd=accm_days,
          accm_val2=lpoint_review,
          accm_val3=lpoint_photo,
          accm_val4=lpoint_video,
        )
        logger.info(f"[롯데ON] L.POINT 적립 설정 완료: {lpoint_accm}P (D+{accm_days}) → {resp}")
      except Exception as e:
        logger.warning(f"[롯데ON] L.POINT 적립 설정 실패 (무시): {e}")

    # ── 살수록할인 ───────────────────────────────────────────────────
    # UI 필드: multiPurchaseDiscount(설정안함/설정함) + multiPurchaseQty(수량) + multiPurchaseRate(할인율%)
    multi_enabled = extras.get("multiPurchaseDiscount") in ("설정함", "true", True, "Y")
    multi_qty = int(extras.get("multiPurchaseQty") or 0)
    multi_rate = float(extras.get("multiPurchaseRate") or 0)
    if multi_enabled and multi_qty > 0 and multi_rate > 0:
      try:
        # 기존 살수록할인 prNo 조회 → 있으면 update(U), 없으면 create(C)
        existing_pr_no = ""
        try:
          search_resp = await client.search_quantity_discount_list(spd_no)
          pr_list = (search_resp.get("data") or {}).get("prList") or []
          if pr_list:
            existing_pr_no = str(pr_list[0].get("prNo", ""))
            logger.info(f"[롯데ON] 기존 살수록할인 발견: prNo={existing_pr_no} → 수정 모드(U)")
        except Exception as se:
          logger.info(f"[롯데ON] 살수록할인 목록 조회 실패 (신규 등록 진행): {se}")

        resp = await client.insert_quantity_discount(
          spd_no,
          min_qty=multi_qty,
          discount_rate=multi_rate,
          eitm_nos=eitm_nos or [],
          pr_no=existing_pr_no,
        )
        logger.info(f"[롯데ON] 살수록할인 설정 완료: {multi_qty}개 이상 {multi_rate}% → {resp}")
      except Exception as e:
        err_str = str(e)
        if "3000" in err_str:
          # 3000 = 행사기간 중복 → 이미 등록된 살수록할인이 활성 상태
          logger.info(f"[롯데ON] 살수록할인 이미 등록됨 — 기존 설정 유지 ({err_str[:80]})")
        else:
          logger.warning(f"[롯데ON] 살수록할인 설정 실패 (무시): {e}")

  async def delete(self, session, product_no: str, account) -> dict[str, Any]:
    """롯데ON 상품 판매중지 (SOUT 상태 변경)."""
    from backend.domain.samba.proxy.lotteon import LotteonClient

    creds = await self._load_auth(session, account)
    if not creds:
      return {"success": False, "message": "롯데ON 인증정보 없음"}

    api_key = creds.get("apiKey", "")
    if not api_key:
      return {"success": False, "message": "롯데ON API Key 없음"}

    try:
      client = LotteonClient(api_key)
      await client.test_auth()
      # END = 판매 종료 (롯데ON은 완전 삭제 API 없음, END가 가장 강한 종료 처리)
      await client.change_status([{"spdNo": product_no, "slStatCd": "SOUT"}])
      return {"success": True, "message": "롯데ON 판매종료 완료"}
    except Exception as e:
      logger.error(f"[롯데ON] 판매종료 실패: {e}")
      return {"success": False, "message": f"롯데ON 판매종료 실패: {e}"}
