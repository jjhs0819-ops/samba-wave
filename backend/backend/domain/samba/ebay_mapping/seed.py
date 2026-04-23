"""eBay 한/영 매핑 기본 시드 데이터."""

# 색상 매핑 (40개)
COLOR_SEED = {
    "검정": "Black",
    "블랙": "Black",
    "검은색": "Black",
    "검정색": "Black",
    "까망": "Black",
    "흰색": "White",
    "화이트": "White",
    "하양": "White",
    "화이트색": "White",
    "빨강": "Red",
    "레드": "Red",
    "빨간색": "Red",
    "레드색": "Red",
    "파랑": "Blue",
    "블루": "Blue",
    "파란색": "Blue",
    "네이비": "Navy",
    "남색": "Navy",
    "노랑": "Yellow",
    "옐로우": "Yellow",
    "노란색": "Yellow",
    "초록": "Green",
    "그린": "Green",
    "녹색": "Green",
    "분홍": "Pink",
    "핑크": "Pink",
    "보라": "Purple",
    "퍼플": "Purple",
    "자주": "Purple",
    "회색": "Gray",
    "그레이": "Gray",
    "그레이색": "Gray",
    "갈색": "Brown",
    "브라운": "Brown",
    "베이지": "Beige",
    "카키": "Khaki",
    "주황": "Orange",
    "오렌지": "Orange",
    "아이보리": "Ivory",
    "실버": "Silver",
    "골드": "Gold",
    "은색": "Silver",
    "금색": "Gold",
    "와인": "Wine",
    "버건디": "Burgundy",
    "민트": "Mint",
    "라벤더": "Lavender",
    "멀티": "Multicolor",
    "멀티컬러": "Multicolor",
    "상세정보참조": "Multicolor",
    "상세 정보 참조": "Multicolor",
    "상세 이미지 참조": "Multicolor",
    "상세이미지참조": "Multicolor",
    "이미지참조": "Multicolor",
    "상세페이지 참고": "Multicolor",
    "상세페이지참고": "Multicolor",
    "상세페이지 참조": "Multicolor",
    "상세페이지참조": "Multicolor",
    "상세 참고": "Multicolor",
    "상세참고": "Multicolor",
    "상세설명참조": "Multicolor",
    "상세설명 참조": "Multicolor",
    "본문참조": "Multicolor",
    "본문 참조": "Multicolor",
    "라벨 참조": "Multicolor",
    "라벨참조": "Multicolor",
    "색상": "Multicolor",
    "컬러": "Multicolor",
    "색깔": "Multicolor",
}

# 소재 매핑 (30개)
MATERIAL_SEED = {
    "면": "Cotton",
    "순면": "Cotton",
    "코튼": "Cotton",
    "가죽": "Leather",
    "천연가죽": "Genuine Leather",
    "인조가죽": "Synthetic Leather",
    "합성가죽": "Synthetic Leather",
    "페이크레더": "Faux Leather",
    "스웨이드": "Suede",
    "메쉬": "Mesh",
    "메시": "Mesh",
    "니트": "Knit",
    "데님": "Denim",
    "청": "Denim",
    "폴리에스터": "Polyester",
    "폴리": "Polyester",
    "나일론": "Nylon",
    "울": "Wool",
    "모": "Wool",
    "캐시미어": "Cashmere",
    "실크": "Silk",
    "린넨": "Linen",
    "리넨": "Linen",
    "플리스": "Fleece",
    "스판": "Spandex",
    "스판덱스": "Spandex",
    "고무": "Rubber",
    "러버": "Rubber",
    "합성섬유": "Synthetic",
    "혼방": "Mixed Materials",
    "혼합소재": "Mixed Materials",
    "상세정보참조": "Mixed Materials",
    "상세 정보 참조": "Mixed Materials",
    "상세 이미지 참조": "Mixed Materials",
    "상세이미지참조": "Mixed Materials",
    "상세페이지 참고": "Mixed Materials",
    "상세페이지참고": "Mixed Materials",
    "상세페이지 참조": "Mixed Materials",
    "상세페이지참조": "Mixed Materials",
    "상세 참고": "Mixed Materials",
    "상세참고": "Mixed Materials",
    "상세설명참조": "Mixed Materials",
    "상세설명 참조": "Mixed Materials",
    "본문참조": "Mixed Materials",
    "본문 참조": "Mixed Materials",
    "라벨 참조": "Mixed Materials",
    "라벨참조": "Mixed Materials",
    "소재": "Mixed Materials",
    "재질": "Mixed Materials",
    "제품 소재": "Mixed Materials",
    "제품소재": "Mixed Materials",
    "원단": "Mixed Materials",
    "재료": "Mixed Materials",
}

# 원산지 매핑 (25개)
ORIGIN_SEED = {
    "대한민국": "South Korea",
    "한국": "South Korea",
    "국산": "South Korea",
    "중국": "China",
    "차이나": "China",
    "일본": "Japan",
    "재팬": "Japan",
    "베트남": "Vietnam",
    "인도네시아": "Indonesia",
    "인도": "India",
    "태국": "Thailand",
    "필리핀": "Philippines",
    "캄보디아": "Cambodia",
    "방글라데시": "Bangladesh",
    "미국": "United States",
    "유에스": "United States",
    "미얀마": "Myanmar",
    "터키": "Turkey",
    "이탈리아": "Italy",
    "프랑스": "France",
    "독일": "Germany",
    "영국": "United Kingdom",
    "스페인": "Spain",
    "포르투갈": "Portugal",
    "멕시코": "Mexico",
    "파키스탄": "Pakistan",
    "대만": "Taiwan",
    "홍콩": "Hong Kong",
    # 의미없는 값 폴백 — China로 (가장 흔한 OEM 원산지)
    "상세정보참조": "China",
    "상세 정보 참조": "China",
    "상세 이미지 참조": "China",
    "상세이미지참조": "China",
    "상세페이지 참고": "China",
    "상세페이지참고": "China",
    "상세페이지 참조": "China",
    "상세페이지참조": "China",
    "상세 참고": "China",
    "상세참고": "China",
    "상세설명참조": "China",
    "상세설명 참조": "China",
    "본문참조": "China",
    "본문 참조": "China",
    "라벨 참조": "China",
    "라벨참조": "China",
    "제조국": "China",
    "원산지": "China",
    "생산지": "China",
    "수입국": "China",
}

# 성별/대상 매핑
SEX_SEED = {
    "남성": "Men",
    "남성용": "Men",
    "남": "Men",
    "맨": "Men",
    "여성": "Women",
    "여성용": "Women",
    "여": "Women",
    "우먼": "Women",
    "공용": "Unisex Adults",
    "남녀공용": "Unisex Adults",
    "남여공용": "Unisex Adults",
    "유니섹스": "Unisex Adults",
    "키즈": "Kids",
    "아동": "Kids",
    "아동용": "Kids",
    "남아": "Boys",
    "여아": "Girls",
    "유아": "Baby",
    "베이비": "Baby",
    "신생아": "Baby",
}

# Type 매핑 (카테고리명 → 영문 상품 타입)
TYPE_SEED = {
    "티셔츠": "T-Shirt",
    "반팔": "T-Shirt",
    "반팔티": "T-Shirt",
    "긴팔티": "Long Sleeve",
    "후드티": "Hoodie",
    "후드": "Hoodie",
    "후드집업": "Hoodie",
    "맨투맨": "Sweatshirt",
    "스웨트셔츠": "Sweatshirt",
    "니트": "Sweater",
    "가디건": "Cardigan",
    "셔츠": "Shirt",
    "남방": "Shirt",
    "블라우스": "Blouse",
    "원피스": "Dress",
    "드레스": "Dress",
    "스커트": "Skirt",
    "치마": "Skirt",
    "플레어스커트": "Skirt",
    "청바지": "Jeans",
    "진": "Jeans",
    "바지": "Pants",
    "슬랙스": "Pants",
    "데님팬츠": "Jeans",
    "데님 팬츠": "Jeans",
    "부츠컷": "Jeans",
    "반바지": "Shorts",
    "쇼츠": "Shorts",
    "트레이닝": "Track Pants",
    "조거": "Jogger Pants",
    "자켓": "Jacket",
    "재킷": "Jacket",
    "윈드자켓": "Windbreaker",
    "바람막이": "Windbreaker",
    "블레이저": "Blazer",
    "코트": "Coat",
    "트렌치": "Trench Coat",
    "패딩": "Puffer Jacket",
    "다운": "Down Jacket",
    "점퍼": "Jacket",
    "베스트": "Vest",
    "조끼": "Vest",
    "플리스": "Fleece",
    "나일론": "Windbreaker",
    "아우터": "Jacket",
    "숏팬츠": "Shorts",
    "롱팬츠": "Pants",
    "조거팬츠": "Jogger Pants",
    "카고팬츠": "Cargo Pants",
    "카고": "Cargo Pants",
    "와이드팬츠": "Pants",
    "레깅스": "Leggings",
    "운동화": "Sneakers",
    "스니커즈": "Sneakers",
    "캔버스화": "Canvas Shoes",
    "로퍼": "Loafers",
    "부츠": "Boots",
    "등산화": "Hiking Shoes",
    "트레킹화": "Trekking Shoes",
    "런닝화": "Running Shoes",
    "러닝화": "Running Shoes",
    "워킹화": "Walking Shoes",
    "아쿠아슈즈": "Water Shoes",
    "스포츠화": "Athletic Shoes",
    "구두": "Dress Shoes",
    "샌들": "Sandals",
    "슬리퍼": "Slippers",
    "장갑": "Gloves",
    "모자": "Hat",
    "캡": "Cap",
    "비니": "Beanie",
    "가방": "Bag",
    "백팩": "Backpack",
    "배낭": "Backpack",
    "에코백": "Tote Bag",
    "크로스백": "Crossbody Bag",
    "지갑": "Wallet",
    "벨트": "Belt",
    "양말": "Socks",
    "목도리": "Scarf",
    "스카프": "Scarf",
    # 시계/액세서리
    "시계": "Watch",
    "손목시계": "Wristwatch",
    "쿼츠": "Quartz Watch",
    "쿼츠 아날로그": "Quartz Watch",
    "아날로그": "Analog Watch",
    "디지털": "Digital Watch",
    "스마트워치": "Smartwatch",
    "시계용품": "Watch Accessories",
    "시계줄": "Watch Band",
    "스마트워치 액세서리": "Smartwatch Accessories",
    # 뷰티/미용
    "헤어소품": "Hair Accessories",
    "미용소품": "Beauty Accessories",
    # 쥬얼리/액세서리
    "반지": "Ring",
    "목걸이": "Necklace",
    "팔찌": "Bracelet",
    "귀걸이": "Earrings",
    "이어링": "Earrings",
    "브로치": "Brooch",
    # 신발 추가
    "슬립온": "Slip-On Shoes",
    "패션스니커즈화": "Sneakers",
    # 스커트
    "미디스커트": "Skirt",
    "롱스커트": "Skirt",
    "미니스커트": "Skirt",
    # 팬츠 추가
    "일자 팬츠": "Pants",
    "일자팬츠": "Pants",
}


BRAND_SEED = {
    "푸마": "PUMA",
    "나이키": "Nike",
    "아디다스": "Adidas",
    "뉴발란스": "New Balance",
    "리복": "Reebok",
    "아식스": "ASICS",
    "언더아머": "Under Armour",
    "컨버스": "Converse",
    "반스": "Vans",
    "휠라": "FILA",
    "구찌": "Gucci",
    "프라다": "Prada",
    "루이비통": "Louis Vuitton",
    "샤넬": "Chanel",
    "에르메스": "Hermes",
    "버버리": "Burberry",
    "톰브라운": "Thom Browne",
    "발렌시아가": "Balenciaga",
    "발렌티노": "Valentino",
    "지방시": "Givenchy",
    "디올": "Dior",
    "몽클레어": "Moncler",
    "캐나다구스": "Canada Goose",
    "노스페이스": "The North Face",
    "파타고니아": "Patagonia",
    "콜롬비아": "Columbia",
    "라코스테": "Lacoste",
    "폴로": "Polo Ralph Lauren",
    "랄프로렌": "Polo Ralph Lauren",
    "타미힐피거": "Tommy Hilfiger",
    "캘빈클라인": "Calvin Klein",
    "유니클로": "Uniqlo",
    "자라": "Zara",
    "에이치앤엠": "H&M",
    "스파오": "SPAO",
    "에잇세컨즈": "8seconds",
    "무신사스탠다드": "Musinsa Standard",
    "밀레": "Millet",
    "밀레골프": "Millet Golf",
    "라이프워크": "Lifework",
    "블랙야크": "Black Yak",
    "네파": "NEPA",
    "K2": "K2",
    "케이투": "K2",
    "코오롱스포츠": "Kolon Sport",
}

# 한국 사이즈(mm) → US 신발 사이즈 매핑
SHOE_SIZE_KR_TO_US_MEN = {
    "220": "4.5",
    "225": "5",
    "230": "5.5",
    "235": "6",
    "240": "6.5",
    "245": "7",
    "250": "7.5",
    "255": "8",
    "260": "8.5",
    "265": "9",
    "270": "9.5",
    "275": "10",
    "280": "10.5",
    "285": "11",
    "290": "11.5",
    "295": "12",
    "300": "12.5",
    "305": "13",
    "310": "13.5",
}

SHOE_SIZE_KR_TO_US_WOMEN = {
    "220": "5",
    "225": "5.5",
    "230": "6",
    "235": "6.5",
    "240": "7",
    "245": "7.5",
    "250": "8",
    "255": "8.5",
    "260": "9",
    "265": "9.5",
    "270": "10",
    "275": "10.5",
    "280": "11",
}


def convert_clothing_size_kr_to_us(kr_size: str, gender: str = "Men") -> str:
    """한국 의류 사이즈(가슴둘레 cm) → US 표준 사이즈 변환. 범위 기반.

    kr_size: "095", "081", "100", "FREE" 등
    gender: "Men" | "Women"
    """
    if not kr_size:
        return ""

    s = str(kr_size).strip().upper()

    # FREE, F 사이즈 → One Size
    if s in ("FREE", "F", "ONE SIZE", "ONESIZE", "ONE", "프리"):
        return "One Size"

    import re

    m = re.search(r"\d+", s)
    if not m:
        return ""
    num = int(m.group())

    # Men's (가슴둘레 cm)
    if "Women" not in gender:
        if num < 82:
            return "XS"
        if num < 87:
            return "S"
        if num < 92:
            return "M"
        if num < 97:
            return "L"
        if num < 102:
            return "XL"
        if num < 107:
            return "XXL"
        if num < 112:
            return "3XL"
        return "4XL"
    # Women's
    if num < 60:
        return "XS"
    if num < 68:
        return "S"
    if num < 76:
        return "M"
    if num < 84:
        return "L"
    if num < 92:
        return "XL"
    return "XXL"


def get_all_seeds() -> list[dict]:
    """모든 시드 데이터를 (category, kr, en) 튜플 리스트로 반환."""
    all_seeds = []
    for category, mapping in [
        ("color", COLOR_SEED),
        ("material", MATERIAL_SEED),
        ("origin", ORIGIN_SEED),
        ("sex", SEX_SEED),
        ("type", TYPE_SEED),
        ("brand", BRAND_SEED),
    ]:
        for kr, en in mapping.items():
            all_seeds.append(
                {
                    "category": category,
                    "kr_value": kr,
                    "en_value": en,
                    "source": "default",
                }
            )
    return all_seeds


def extract_season(korean_text: str) -> str:
    """한글 season 컬럼에서 eBay 표준 Season aspect 추출.

    예시:
      "2025 SS" → "Spring/Summer"
      "2024 ALL" → "All Seasons"
      "2025 FW" → "Fall/Winter"
    """
    if not korean_text:
        return ""
    text = str(korean_text).upper()
    if "SS" in text or "S/S" in text or "봄여름" in text or "봄/여름" in text:
        return "Spring/Summer"
    if "FW" in text or "F/W" in text or "가을겨울" in text or "가을/겨울" in text:
        return "Fall/Winter"
    if "ALL" in text or "사계절" in text or "4계절" in text or "연중" in text:
        return "All Seasons"
    if "봄" in korean_text or "SPRING" in text:
        return "Spring"
    if "여름" in korean_text or "SUMMER" in text:
        return "Summer"
    if "가을" in korean_text or "FALL" in text or "AUTUMN" in text:
        return "Fall"
    if "겨울" in korean_text or "WINTER" in text:
        return "Winter"
    return ""


def extract_care_code(korean_text: str) -> str:
    """한글 care_instructions에서 eBay 표준 Garment Care code 추출.

    키워드 우선순위: 구체적 → 일반적
    """
    if not korean_text:
        return ""
    text = str(korean_text).lower()

    # 드라이클리닝
    if any(k in text for k in ["드라이클리닝", "드라이 클리닝", "드라이 크리닝"]):
        return "Dry Clean Only"
    # 손세탁
    if any(k in text for k in ["손세탁", "손빨래", "손 세탁", "손 빨래", "hand wash"]):
        return "Hand Wash Only"
    # 세탁기 (손세탁 아닌 경우)
    if any(k in text for k in ["세탁기", "기계 세탁", "machine wash"]):
        return "Machine Washable"
    # 드라이 (단독)
    if "드라이" in text:
        return "Dry Clean Only"
    # 세탁 불가
    if any(k in text for k in ["세탁 불가", "세탁불가", "세탁금지"]):
        return "Dry Clean Only"
    # 상세 설명 폴백
    if any(k in text for k in ["상세", "참조", "문의", "제품 라벨", "라벨 참조"]):
        return "See product description"
    return "See product description"


def convert_shoe_size_kr_to_us(kr_size: str, gender: str = "Men") -> str:
    """한국 신발 사이즈(mm) → US 사이즈 변환.

    kr_size: "250", "260" 등
    gender: "Men" | "Women"
    """
    if not kr_size:
        return ""
    # 숫자만 추출
    import re

    m = re.search(r"\d+", str(kr_size))
    if not m:
        return ""
    num = m.group()
    table = SHOE_SIZE_KR_TO_US_WOMEN if "Women" in gender else SHOE_SIZE_KR_TO_US_MEN
    return table.get(num, "")
