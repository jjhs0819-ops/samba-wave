"""신규 Brand Risk System 공용 상수 — IP위험 / 쿠팡 사전소명 / 신뢰도 / 이미지상태 / 경험유형.

RISK_RULES.md v2(2026-08-11 기준)의 판정 체계를 코드 상수로 그대로 옮긴 것이다.

기존 SambaBrandRestriction.verdict(blocked/allowed/unknown, brand/model.py)는
건드리지 않는다 — 여기 상수들은 같은 테이블에 Phase 1에서 추가된 "새 축"
전용이며, BrandGuardService.check()는 여전히 기존 verdict만 읽는다.
새 축을 실제 판정 로직에 연결하는 건 이후 Phase 몫이다.
"""

# ── IP Risk (지재권/신고 위험) ──
IP_RISK_BLOCK_STRONG = "BLOCK_STRONG"
IP_RISK_BLOCK = "BLOCK"
IP_RISK_CAUTION = "CAUTION"
IP_RISK_NO_RISK_FOUND = "NO_RISK_FOUND"
IP_RISK_REVIEW_REQUIRED = "REVIEW_REQUIRED"
IP_RISK_UNKNOWN = "UNKNOWN"

IP_RISK_LEVELS = (
    IP_RISK_BLOCK_STRONG,
    IP_RISK_BLOCK,
    IP_RISK_CAUTION,
    IP_RISK_NO_RISK_FOUND,
    IP_RISK_REVIEW_REQUIRED,
    IP_RISK_UNKNOWN,
)

# ── Coupang Pre-Authorization (쿠팡 사전소명) ──
# IP Risk 와 완전히 독립된 축이다. "패스 = 지재권 안전"이 아니고
# "지재권 위험 없음 = 사전소명 불필요"도 아니다(RISK_RULES.md 절대 규칙).
COUPANG_PRE_AUTH_REQUIRED = "REQUIRED"
COUPANG_PRE_AUTH_NOT_REQUIRED = "NOT_REQUIRED"
COUPANG_PRE_AUTH_UNKNOWN = "UNKNOWN"

COUPANG_PRE_AUTH_STATES = (
    COUPANG_PRE_AUTH_REQUIRED,
    COUPANG_PRE_AUTH_NOT_REQUIRED,
    COUPANG_PRE_AUTH_UNKNOWN,
)

# ── 근거 신뢰도 ──
CONFIDENCE_A = "A"  # 직접 경험 + 실제 메일/문자/화면/구체 사건
CONFIDENCE_B = "B"  # 직접 경험의 구체적 진술
CONFIDENCE_C = "C"  # 타 판매자 경험 전달 / 금지어 목록
CONFIDENCE_D = "D"  # 소문·추측·질문 (D 단독으로 BLOCK 불가)
CONFIDENCE_UNKNOWN = "UNKNOWN"

CONFIDENCE_LEVELS = (
    CONFIDENCE_A,
    CONFIDENCE_B,
    CONFIDENCE_C,
    CONFIDENCE_D,
    CONFIDENCE_UNKNOWN,
)

# ── 사건 경험 유형 (RISK_RULES.md 신규 사건 스키마) ──
EXPERIENCE_DIRECT = "DIRECT"
EXPERIENCE_RELAY = "RELAY"
EXPERIENCE_RUMOR = "RUMOR"

EXPERIENCE_TYPES = (EXPERIENCE_DIRECT, EXPERIENCE_RELAY, EXPERIENCE_RUMOR)

# ── 이미지 상태 (RISK_RULES.md 신규 사건 스키마) ──
# 사건(case) 단위 속성이다 — 브랜드 전체를 하나의 이미지 상태로 요약하지
# 않는다. 같은 브랜드에서도 사건마다 원본/누끼/AI변환이 섞여 있고, 강제로
# 하나만 남기면 "현재 문서의 사건정보를 손실 없이 담는다"는 원칙과 상충한다.
IMAGE_ORIGINAL = "ORIGINAL"
IMAGE_CUTOUT = "CUTOUT"
IMAGE_CROPPED = "CROPPED"
IMAGE_AI_TRANSFORMED = "AI_TRANSFORMED"
IMAGE_DIRECT_PHOTO = "DIRECT_PHOTO"
IMAGE_UNKNOWN = "UNKNOWN"

IMAGE_STATES = (
    IMAGE_ORIGINAL,
    IMAGE_CUTOUT,
    IMAGE_CROPPED,
    IMAGE_AI_TRANSFORMED,
    IMAGE_DIRECT_PHOTO,
    IMAGE_UNKNOWN,
)
