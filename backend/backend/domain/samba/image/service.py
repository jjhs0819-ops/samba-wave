"""이미지 변환 서비스 — Gemini AI + Cloudflare R2/로컬 저장."""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import uuid
from pathlib import Path
from typing import Any

import httpx
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)

# 로컬 저장 경로
LOCAL_IMAGE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "static" / "images"
LOCAL_IMAGE_DIR.mkdir(parents=True, exist_ok=True)

# 프리셋 이미지 로컬 경로
PRESET_IMAGE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "static" / "model_presets"

# ──────────────────────────────────────────────
# 모델 프리셋 (12개) — image: 참조 이미지 파일명
# ──────────────────────────────────────────────
MODEL_PRESETS: dict[str, dict[str, str]] = {
  # 성인 여성
  "female_v1": {
    "label": "성인여성 — 청순 생머리",
    "desc": "25세 한국인 여성, 어깨 아래 긴 생머리, 슬림 체형, 165cm, 환한 미소, 한쪽 손 주머니에 넣은 포즈, 밝은 피부",
    "image": "female_v1.png",
  },
  "female_v2": {
    "label": "성인여성 — 시크 단발",
    "desc": "25세 한국인 여성, 귀 아래 짧은 단발, 슬림 체형, 163cm, 차분하고 세련된 분위기, 양손 자연스럽게 내린 포즈",
    "image": "female_v2.png",
  },
  "female_v3": {
    "label": "성인여성 — 건강 웨이브",
    "desc": "25세 한국인 여성, 어깨 아래 긴 웨이브 갈색머리, 슬림 체형, 167cm, 밝고 건강한 미소, 한쪽 손 주머니에 넣은 포즈",
    "image": "female_v3.png",
  },
  # 성인 남성
  "male_v1": {
    "label": "성인남성 — 깔끔 슬림",
    "desc": "27세 한국인 남성, 짧은 앞머리 내린 스타일, 슬림 체형, 176cm, 밝은 미소, 라이트그레이 슬랙스 착용, 깔끔한 느낌",
    "image": "male_v1.png",
  },
  "male_v2": {
    "label": "성인남성 — 남성미 근육",
    "desc": "27세 한국인 남성, 짧은 투블럭 머리, 넓은 어깨 근육질 체형, 180cm, 진지한 표정, 검은색 슬랙스 착용, 강인한 분위기",
    "image": "male_v2.png",
  },
  "male_v3": {
    "label": "성인남성 — 훈남 스타일",
    "desc": "27세 한국인 남성, 자연스러운 가르마 머리, 슬림 체형, 178cm, 부드러운 미소, 한쪽 손 주머니에 넣은 포즈, 따뜻한 훈남 이미지",
    "image": "male_v3.png",
  },
  # 키즈 여아
  "kids_girl_v1": {
    "label": "키즈여아 — 긴머리 차분",
    "desc": "8세 한국인 여아, 어깨 아래 긴 생머리, 130cm, 차분하게 서있는 포즈, 양손 자연스럽게 내림",
    "image": "kids_girl_v1.png",
  },
  "kids_girl_v2": {
    "label": "키즈여아 — 단발 활발",
    "desc": "8세 한국인 여아, 턱선 단발머리, 128cm, 양팔 벌린 활발한 포즈, 밝은 표정",
    "image": "kids_girl_v2.png",
  },
  "kids_girl_v3": {
    "label": "키즈여아 — 양갈래 귀여움",
    "desc": "8세 한국인 여아, 양갈래 묶은머리, 130cm, 귀여운 미소, 자연스러운 포즈",
    "image": "kids_girl_v3.png",
  },
  # 키즈 남아
  "kids_boy_v1": {
    "label": "키즈남아 — 밝은 정면",
    "desc": "8세 한국인 남아, 짧은 머리, 130cm, 밝은 미소, 양손 주머니에 넣고 정면 포즈",
    "image": "kids_boy_v1.png",
  },
  "kids_boy_v2": {
    "label": "키즈남아 — 장난꾸러기",
    "desc": "8세 한국인 남아, 짧은 머리, 128cm, 한쪽 다리 들고 점프하는 역동적 포즈, 장난꾸러기 표정",
    "image": "kids_boy_v2.png",
  },
  "kids_boy_v3": {
    "label": "키즈남아 — 차분한",
    "desc": "8세 한국인 남아, 약간 긴 앞머리, 130cm, 양손 내리고 차분하게 서있는 포즈, 반바지 착용",
    "image": "kids_boy_v3.png",
  },
}

# ──────────────────────────────────────────────
# 카테고리별 프롬프트 템플릿
# ──────────────────────────────────────────────
def _get_category_prompt(category: str, mode: str, model_desc: str) -> str:
  """카테고리 + 모드 + 모델 프리셋으로 프롬프트 생성."""
  cat_lower = (category or "").lower()

  # 카테고리 감지
  if any(k in cat_lower for k in ["등산화", "트레킹"]):
    cat_type = "hiking_shoes"
  elif any(k in cat_lower for k in ["런닝화", "러닝화", "운동화", "스니커즈", "스포츠화"]):
    cat_type = "sneakers"
  elif any(k in cat_lower for k in ["구두", "로퍼", "옥스포드", "더비"]):
    cat_type = "dress_shoes"
  elif any(k in cat_lower for k in ["샌들", "슬리퍼"]):
    cat_type = "sandals"
  elif any(k in cat_lower for k in ["부츠"]):
    cat_type = "boots"
  elif any(k in cat_lower for k in ["신발"]):
    cat_type = "shoes"
  elif any(k in cat_lower for k in ["아우터", "자켓", "재킷", "코트", "점퍼", "패딩", "윈드"]):
    cat_type = "outer"
  elif any(k in cat_lower for k in ["상의", "셔츠", "니트", "티셔츠", "블라우스", "맨투맨", "후드"]):
    cat_type = "top"
  elif any(k in cat_lower for k in ["하의", "바지", "팬츠", "스커트", "치마", "레깅스"]):
    cat_type = "bottom"
  elif any(k in cat_lower for k in ["가방", "백팩", "토트", "크로스백", "숄더백"]):
    cat_type = "bag"
  elif any(k in cat_lower for k in ["모자", "캡", "비니", "버킷햇"]):
    cat_type = "hat"
  elif any(k in cat_lower for k in ["뷰티", "화장품", "스킨케어", "향수"]):
    cat_type = "beauty"
  else:
    cat_type = "general"

  if mode == "background":
    return "이 상품 사진에서 배경을 제거하고, 순수 흰색 배경 위에 상품만 깔끔하게 배치해주세요. 상품의 색상, 디자인, 디테일을 100% 정확하게 유지해주세요. 그림자 없이 깨끗하게."

  if mode == "scene":
    scene_map = {
      "hiking_shoes": "산길 옆 나무 벤치 위에 자연스럽게 놓인 모습, 아웃도어 감성",
      "sneakers": "카페 테이블 위에 깔끔하게 놓인 플랫레이, 미니멀한 라이프스타일",
      "dress_shoes": "대리석 바닥 위에 우아하게 놓인 모습, 고급스러운 분위기",
      "sandals": "해변가 모래 위, 여름 감성, 자연광",
      "boots": "가을 낙엽 위에 놓인 모습, 따뜻한 톤",
      "shoes": "깔끔한 나무 바닥 위에 놓인 모습",
      "outer": "옷걸이에 걸린 모습, 깔끔한 옷장 배경",
      "top": "깔끔하게 접혀서 나무 선반 위에 놓인 플랫레이",
      "bottom": "깔끔하게 접혀서 놓인 플랫레이, 미니멀 배경",
      "bag": "카페 테이블 위에 자연스럽게 놓인 모습, 소품과 함께",
      "hat": "나무 테이블 위에 놓인 모습, 자연광",
      "beauty": "대리석 위에 놓인 모습, 꽃잎 장식, 고급스러운 뷰티 화보",
      "general": "깔끔한 배경에 자연스럽게 배치된 제품 사진",
    }
    scene = scene_map.get(cat_type, scene_map["general"])
    return f"이 상품 사진을 참고해서, {scene} 연출컷을 만들어주세요. 상품의 색상, 디자인, 로고, 디테일을 100% 정확하게 유지해주세요. 전문 매거진 에디토리얼 스타일."

  # mode == "video" — 영상용 전신 라이프스타일 연출
  if mode == "video":
    video_map = {
      "hiking_shoes": f"이 등산화 사진을 참고해서, {model_desc}이(가) 이 신발을 신고 산길을 걷고 있는 전신 사진을 생성해주세요. 등산복 차림, 자연스러운 산속 배경, 나무와 흙길, 자연광, 아웃도어 라이프스타일 감성.",
      "sneakers": f"이 운동화 사진을 참고해서, {model_desc}이(가) 이 신발을 신고 도심 거리를 걷고 있는 전신 사진을 생성해주세요. 캐주얼 코디, 카페 거리/도심 보도, 자연스러운 워킹 포즈, 스트릿 패션 감성.",
      "dress_shoes": f"이 구두 사진을 참고해서, {model_desc}이(가) 이 구두를 신고 서 있는 전신 사진을 생성해주세요. 정장/슬랙스 코디, 고급 로비나 대리석 바닥, 비즈니스 캐주얼 분위기.",
      "sandals": f"이 샌들 사진을 참고해서, {model_desc}이(가) 이 샌들을 신고 해변가를 걷고 있는 전신 사진을 생성해주세요. 여름 캐주얼 코디, 모래사장/보드워크 배경, 밝은 자연광.",
      "boots": f"이 부츠 사진을 참고해서, {model_desc}이(가) 이 부츠를 신고 가을 거리에 서 있는 전신 사진을 생성해주세요. 코트/니트 매치, 낙엽이 있는 공원길, 따뜻한 톤.",
      "shoes": f"이 신발 사진을 참고해서, {model_desc}이(가) 이 신발을 신고 깔끔한 거리를 걷고 있는 전신 사진을 생성해주세요. 캐주얼 코디, 도심 배경, 자연스러운 포즈.",
      "outer": f"이 아우터 사진을 참고해서, {model_desc}이(가) 이 아우터를 입고 도심 거리를 걷고 있는 전신 사진을 생성해주세요. 심플한 이너, 가로수길/도심 배경, 바람에 살짝 날리는 느낌.",
      "top": f"이 상의 사진을 참고해서, {model_desc}이(가) 이 옷을 입고 카페에 앉아 있는 전신 사진을 생성해주세요. 자연스러운 일상 포즈, 밝고 깔끔한 카페 인테리어 배경.",
      "bottom": f"이 하의 사진을 참고해서, {model_desc}이(가) 이 옷을 입고 거리를 걷고 있는 전신 사진을 생성해주세요. 심플한 상의 매치, 도심/공원 배경, 자연스러운 워킹 포즈.",
      "bag": f"이 가방 사진을 참고해서, {model_desc}이(가) 이 가방을 메고 거리를 걷고 있는 전신 사진을 생성해주세요. 캐주얼 코디, 도심 쇼핑거리 배경, 자연스러운 포즈.",
      "hat": f"이 모자 사진을 참고해서, {model_desc}이(가) 이 모자를 쓰고 야외에서 포즈를 취하고 있는 전신 사진을 생성해주세요. 캐주얼 코디, 공원/거리 배경, 밝은 자연광.",
      "beauty": f"이 뷰티 제품 사진을 참고해서, {model_desc}이(가) 이 제품을 손에 들고 화장대 앞에 앉아 있는 상반신 사진을 생성해주세요. 밝은 조명, 깔끔한 뷰티룸 배경.",
      "general": f"이 상품 사진을 참고해서, {model_desc}이(가) 이 상품을 사용하고 있는 전신 사진을 생성해주세요. 자연스러운 일상 공간 배경, 라이프스타일 감성.",
    }
    prompt = video_map.get(cat_type, video_map["general"])
    return prompt + " 상품의 색상, 디자인, 로고, 디테일을 100% 정확하게 유지해주세요. 전문 패션 화보 스타일, 9:16 세로 구도."

  # mode == "model"
  model_prompt_map = {
    "hiking_shoes": f"이 등산화 사진을 참고해서, {model_desc}이(가) 이 신발을 착용한 발 클로즈업 사진을 생성해주세요. 무릎 아래만 보이는 구도, 등산복/카고팬츠에 흰색 양말, 측면 각도, 라이트그레이 배경.",
    "sneakers": f"이 운동화 사진을 참고해서, {model_desc}이(가) 이 신발을 착용한 발 클로즈업 사진을 생성해주세요. 무릎 아래만 보이는 구도, 조거팬츠에 숏양말, 측면 각도, 깔끔한 배경.",
    "dress_shoes": f"이 구두 사진을 참고해서, {model_desc}이(가) 이 신발을 착용한 발 클로즈업 사진을 생성해주세요. 무릎 아래만 보이는 구도, 정장바지/슬랙스, 측면 각도, 깔끔한 배경.",
    "sandals": f"이 샌들 사진을 참고해서, {model_desc}이(가) 이 신발을 착용한 발 클로즈업 사진을 생성해주세요. 무릎 아래만 보이는 구도, 맨발, 측면 각도, 밝은 배경.",
    "boots": f"이 부츠 사진을 참고해서, {model_desc}이(가) 이 부츠를 착용한 사진을 생성해주세요. 무릎 아래만 보이는 구도, 스키니진/원피스, 측면 각도, 깔끔한 배경.",
    "shoes": f"이 신발 사진을 참고해서, {model_desc}이(가) 이 신발을 착용한 발 클로즈업 사진을 생성해주세요. 무릎 아래만 보이는 구도, 흰 양말, 측면 각도, 깔끔한 배경.",
    "outer": f"이 아우터 사진을 참고해서, {model_desc}이(가) 이 아우터를 입고 있는 상반신 사진을 생성해주세요. 안에 심플한 흰 티셔츠, 자연스러운 포즈, 흰색 스튜디오 배경.",
    "top": f"이 상의 사진을 참고해서, {model_desc}이(가) 이 옷을 입고 있는 상반신 사진을 생성해주세요. 자연스러운 포즈, 흰색 스튜디오 배경, 전문 패션 화보 스타일.",
    "bottom": f"이 하의 사진을 참고해서, {model_desc}이(가) 이 옷을 입고 있는 전신 사진을 생성해주세요. 심플한 흰 티셔츠 매치, 자연스러운 포즈, 흰색 스튜디오 배경.",
    "bag": f"이 가방 사진을 참고해서, {model_desc}이(가) 이 가방을 들고/메고 있는 상반신 사진을 생성해주세요. 심플한 의상, 자연스러운 포즈, 흰색 스튜디오 배경.",
    "hat": f"이 모자 사진을 참고해서, {model_desc}이(가) 이 모자를 쓰고 있는 상반신 사진을 생성해주세요. 심플한 의상, 자연스러운 포즈, 흰색 스튜디오 배경.",
    "beauty": f"이 뷰티 제품 사진을 참고해서, {model_desc}이(가) 이 제품을 손에 들고 있는 클로즈업 사진을 생성해주세요. 깨끗한 피부, 자연스러운 포즈, 밝은 배경.",
    "general": f"이 상품 사진을 참고해서, {model_desc}이(가) 이 상품을 사용/착용하고 있는 사진을 생성해주세요. 자연스러운 포즈, 흰색 스튜디오 배경.",
  }
  prompt = model_prompt_map.get(cat_type, model_prompt_map["general"])
  return prompt + " 상품의 색상, 디자인, 로고, 디테일을 100% 정확하게 유지해주세요. 전문 패션 화보 스타일."


class ImageTransformService:
  """Gemini AI를 통한 이미지 변환 + R2/로컬 저장."""

  def __init__(self, session: AsyncSession) -> None:
    self.session = session

  async def _get_setting(self, key: str) -> dict[str, Any] | None:
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository
    repo = SambaSettingsRepository(self.session)
    row = await repo.find_by_async(key=key)
    if row and isinstance(row.value, dict):
      return row.value
    return None

  async def _get_gemini_config(self) -> tuple[str, str]:
    """Gemini API 키, 모델 반환."""
    creds = await self._get_setting("gemini")
    if not creds:
      raise ValueError("Gemini AI 설정이 없습니다. 설정 페이지에서 API Key를 입력하세요.")
    api_key = str(creds.get("apiKey", "")).strip()
    model = str(creds.get("model", "gemini-2.5-flash-image"))
    if not api_key:
      raise ValueError("Gemini API Key가 비어있습니다.")
    return api_key, model

  async def _get_r2_client(self) -> tuple[Any, str, str] | None:
    """R2 설정이 있으면 boto3 클라이언트 반환, 없으면 None."""
    creds = await self._get_setting("cloudflare_r2")
    if not creds:
      return None
    account_id = str(creds.get("accountId", "")).strip()
    access_key = str(creds.get("accessKey", "")).strip()
    secret_key = str(creds.get("secretKey", "")).strip()
    bucket_name = str(creds.get("bucketName", "")).strip()
    public_url = str(creds.get("publicUrl", "")).strip().rstrip("/")
    if not access_key or not secret_key or not bucket_name:
      return None
    try:
      import boto3
      client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
      )
      return client, bucket_name, public_url
    except Exception:
      return None

  async def _download_image(self, url: str) -> bytes:
    """이미지 URL에서 바이트 다운로드."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"
    if "msscdn.net" in (parsed.netloc or ""):
      referer = "https://www.musinsa.com/"

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
      resp = await client.get(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": referer,
      })
      resp.raise_for_status()
      if len(resp.content) < 1000:
        raise ValueError(f"이미지가 비정상적으로 작음({len(resp.content)}B)")
      return resp.content

  @staticmethod
  def _is_product_image(url: str, image_bytes: bytes | None = None) -> bool:
    """URL 패턴 + 이미지 비율로 상품 사진 여부 판별.

    배너, 로고, 브랜드 소개 등 비상품 이미지를 걸러낸다.
    """
    url_lower = url.lower()

    # URL 패턴 필터 — 배너/로고/광고 이미지 제외
    skip_patterns = [
      "brand_intro", "brand_logo", "brand_banner",
      "ad_brand", "ad_logo", "ad_banner",
      "/banner/", "/logo/", "/event/", "/promotion/",
      "/ad/", "/ads/", "/advert/",
      "logo_", "banner_", "btn_", "icon_",
      "size_guide", "sizeguide", "size_chart",
      "delivery_info", "shipping_info",
      "notice", "caution", "warning",
    ]
    for pat in skip_patterns:
      if pat in url_lower:
        return False

    # 이미지 비율 체크 — 극단적 가로/세로 비율이면 배너로 판단
    if image_bytes and len(image_bytes) > 100:
      try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size
        if w > 0 and h > 0:
          ratio = w / h
          # 가로가 3배 이상 넓으면 배너 (예: 1200x200)
          if ratio > 3.0:
            return False
          # 세로가 5배 이상 길면 안내 이미지
          if ratio < 0.2:
            return False
          # 너무 작은 이미지 (아이콘 등)
          if w < 100 or h < 100:
            return False
      except Exception:
        pass

    return True

  @staticmethod
  def _detect_mime(data: bytes) -> str:
    """이미지 바이트에서 MIME 타입 감지."""
    if data[:4] == b"\x89PNG":
      return "image/png"
    if data[:4] == b"RIFF":
      return "image/webp"
    return "image/jpeg"

  async def _load_preset_image(self, preset_key: str) -> bytes | None:
    """프리셋 참조 이미지 로드 — 로컬 → R2 CDN 순서로 fallback."""
    preset = MODEL_PRESETS.get(preset_key)
    if not preset or not preset.get("image"):
      return None

    filename = preset["image"]

    # 1) 로컬 파일 확인
    local_path = PRESET_IMAGE_DIR / filename
    if local_path.exists():
      logger.info(f"[프리셋] 로컬에서 로드: {local_path}")
      return local_path.read_bytes()

    # 2) R2 CDN에서 다운로드
    r2 = await self._get_r2_client()
    if r2:
      _, _, public_url = r2
      cdn_url = f"{public_url}/model_presets/{filename}"
      try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
          resp = await client.get(cdn_url)
          resp.raise_for_status()
          if len(resp.content) > 1000:
            logger.info(f"[프리셋] R2 CDN에서 로드: {cdn_url}")
            return resp.content
      except Exception as e:
        logger.warning(f"[프리셋] R2 CDN 다운로드 실패: {e}")

    # 3) 참조 이미지 없음 — 텍스트 프롬프트만 사용
    logger.warning(f"[프리셋] 참조 이미지 없음 ({filename}), 텍스트만 사용")
    return None

  async def _transform_image_gemini(
    self, api_key: str, model: str, image_bytes: bytes,
    prompt: str, ref_image_bytes: bytes | None = None,
  ) -> bytes:
    """Gemini API로 이미지 변환. 참조 모델 이미지가 있으면 함께 전송."""
    parts: list[dict[str, Any]] = []

    # 참조 모델 이미지가 있으면 먼저 추가
    if ref_image_bytes:
      ref_prompt = (
        "첫 번째 이미지는 참조 모델입니다. "
        "이 모델과 동일한 얼굴, 체형, 분위기를 유지하면서 "
        "두 번째 상품 이미지의 옷/신발을 착용한 사진을 생성해주세요. "
      )
      parts.append({"text": ref_prompt + prompt})
      parts.append({
        "inline_data": {
          "mime_type": self._detect_mime(ref_image_bytes),
          "data": base64.b64encode(ref_image_bytes).decode("ascii"),
        }
      })
    else:
      parts.append({"text": prompt})

    # 상품 이미지 추가
    parts.append({
      "inline_data": {
        "mime_type": self._detect_mime(image_bytes),
        "data": base64.b64encode(image_bytes).decode("ascii"),
      }
    })

    body = {
      "contents": [{"parts": parts}],
      "generationConfig": {
        "responseModalities": ["TEXT", "IMAGE"],
      },
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    async with httpx.AsyncClient(timeout=120) as client:
      resp = await client.post(url, json=body, headers={"Content-Type": "application/json"})
      resp.raise_for_status()
      data = resp.json()

      candidates = data.get("candidates", [])
      if not candidates:
        raise ValueError("Gemini 응답에 candidates 없음")

      parts_resp = candidates[0].get("content", {}).get("parts", [])
      for part in parts_resp:
        if "inlineData" in part:
          return base64.b64decode(part["inlineData"]["data"])

      raise ValueError("Gemini 응답에 이미지 없음")

  async def _save_image(self, image_bytes: bytes, original_url: str) -> str:
    """R2 또는 로컬에 이미지 저장 후 URL 반환."""
    url_hash = hashlib.md5(original_url.encode()).hexdigest()[:8]
    filename = f"ai_{url_hash}_{uuid.uuid4().hex[:6]}.webp"

    # R2 저장 시도
    r2 = await self._get_r2_client()
    if r2:
      client, bucket_name, public_url = r2
      try:
        import asyncio as _aio
        from functools import partial
        await _aio.to_thread(
          partial(client.upload_fileobj,
            io.BytesIO(image_bytes), bucket_name, f"transformed/{filename}",
            ExtraArgs={"ContentType": "image/webp"}),
        )
        return f"{public_url}/transformed/{filename}"
      except Exception as e:
        logger.warning(f"[이미지] R2 업로드 실패, 로컬 저장으로 전환: {e}")

    # 로컬 저장
    local_path = LOCAL_IMAGE_DIR / filename
    local_path.write_bytes(image_bytes)
    return f"/static/images/{filename}"

  async def transform_single_image(
    self, product_id: str, image_url: str, mode: str = "video",
    model_preset: str = "female_v1",
  ) -> str | None:
    """단일 이미지를 AI 변환 후 URL 반환. 대표이미지를 건드리지 않는 독립 변환."""
    from backend.domain.samba.collector.repository import SambaCollectedProductRepository
    repo = SambaCollectedProductRepository(self.session)
    product = await repo.get_async(product_id)
    if not product:
      return None

    api_key, model = await self._get_gemini_config()
    preset = MODEL_PRESETS.get(model_preset, MODEL_PRESETS["female_v1"])
    model_desc = preset["desc"]
    ref_image = await self._load_preset_image(model_preset)

    category = " > ".join(filter(None, [
      getattr(product, "category1", ""),
      getattr(product, "category2", ""),
      getattr(product, "category3", ""),
    ]))
    prompt = _get_category_prompt(category, mode, model_desc)

    try:
      img = await self._download_image(image_url)
      transformed = await self._transform_image_gemini(api_key, model, img, prompt, ref_image)
      new_url = await self._save_image(transformed, image_url)
      return new_url
    except Exception as e:
      logger.error(f"[이미지] 단일 변환 실패 ({product_id}): {e}")
      return None

  async def transform_products(
    self,
    product_ids: list[str],
    scope: dict[str, bool],
    mode: str,
    model_preset: str = "female_v1",
  ) -> dict[str, Any]:
    """여러 상품의 이미지를 일괄 변환."""
    from backend.domain.samba.collector.repository import SambaCollectedProductRepository
    repo = SambaCollectedProductRepository(self.session)
    api_key, model = await self._get_gemini_config()

    # 모델 프리셋 설명 + 참조 이미지 로드
    preset = MODEL_PRESETS.get(model_preset, MODEL_PRESETS["female_v1"])
    model_desc = preset["desc"]
    ref_image: bytes | None = None
    if mode == "model":
      ref_image = await self._load_preset_image(model_preset)

    results: list[dict[str, Any]] = []
    total_transformed = 0
    total_failed = 0

    for pid in product_ids:
      product = await repo.get_async(pid)
      if not product:
        results.append({"product_id": pid, "status": "not_found"})
        continue

      # 카테고리 조합
      category = " > ".join(filter(None, [
        getattr(product, "category1", ""),
        getattr(product, "category2", ""),
        getattr(product, "category3", ""),
      ]))

      product_result: dict[str, Any] = {"product_id": pid, "transformed": 0, "failed": 0}
      update_data: dict[str, Any] = {}
      product_images = product.images or []

      # 프롬프트 생성
      prompt = _get_category_prompt(category, mode, model_desc)

      # ── 모델 착용 모드: 대표1장 + 추가3장 고정 생성 ──
      if mode == "model" and product_images:
        # 1) 대표이미지 변환
        new_thumb_url = None
        try:
          img = await self._download_image(product_images[0])
          transformed = await self._transform_image_gemini(api_key, model, img, prompt, ref_image)
          new_thumb_url = await self._save_image(transformed, product_images[0])
          product_result["transformed"] += 1
        except Exception as e:
          logger.error(f"[이미지] {pid} 대표이미지 변환 실패: {e}")
          product_result["failed"] += 1

        # 2) 추가이미지 소스 결정: 추가이미지 있으면 사용, 없으면 상세이미지 참고
        raw_additional = list(product_images[1:]) if len(product_images) > 1 else []

        # URL 패턴으로 비상품 이미지(배너/로고) 1차 필터링
        additional_sources = [u for u in raw_additional if self._is_product_image(u)]
        filtered_count = len(raw_additional) - len(additional_sources)
        if filtered_count > 0:
          logger.info(f"[이미지] {pid} 추가이미지 {filtered_count}장 필터링 (배너/로고 제외)")

        used_detail_as_ref = False
        if not additional_sources:
          # 상세이미지에서 참고용 소스 가져오기 (상세이미지 자체는 변경 안함)
          raw_detail = list(product.detail_images or [])
          additional_sources = [u for u in raw_detail if self._is_product_image(u)]
          used_detail_as_ref = True
          if additional_sources:
            logger.info(f"[이미지] {pid} 추가이미지 없음 → 상세이미지 {len(additional_sources)}장 참고")

        # 3) 소스에서 최대 3개 뽑아 변환 → 추가이미지 3장 생성
        #    다운로드 후 이미지 비율도 2차 검증하여 배너 제거
        new_additional: list[str] = []
        src_idx = 0
        attempts = 0
        max_attempts = max(len(additional_sources) * 2, 6) if additional_sources else 3
        while len(new_additional) < 3 and attempts < max_attempts:
          if additional_sources:
            src_url = additional_sources[src_idx % len(additional_sources)]
            src_idx += 1
          else:
            src_url = product_images[0]
          attempts += 1
          try:
            img = await self._download_image(src_url)
            # 다운로드 후 이미지 비율 2차 검증
            if additional_sources and not self._is_product_image(src_url, img):
              logger.info(f"[이미지] {pid} 비상품 이미지 스킵 (비율 이상): {src_url[:80]}")
              continue
            transformed = await self._transform_image_gemini(api_key, model, img, prompt, ref_image)
            new_url = await self._save_image(transformed, src_url)
            new_additional.append(new_url)
            product_result["transformed"] += 1
          except Exception as e:
            logger.error(f"[이미지] {pid} 추가이미지({len(new_additional)+1}/3) 변환 실패: {e}")
            product_result["failed"] += 1
            # 소스 없으면 더 이상 시도 불필요
            if not additional_sources:
              break

        # 4) 최종: 대표1장 + 추가3장만 남김 (나머지 삭제)
        final_images = [new_thumb_url or product_images[0]] + new_additional
        update_data["images"] = final_images
        # 상세이미지는 그대로 유지 (변경 안함)

      # ── 연출컷 모드 ──
      elif mode == "scene" and product_images:
        has_additional = len(product_images) > 1
        # 대표이미지 변환
        try:
          img = await self._download_image(product_images[0])
          transformed = await self._transform_image_gemini(api_key, model, img, prompt, ref_image)
          new_url = await self._save_image(transformed, product_images[0])
          updated_images = list(product_images)
          updated_images[0] = new_url
          update_data["images"] = updated_images
          product_result["transformed"] += 1
        except Exception as e:
          logger.error(f"[이미지] {pid} 대표이미지 변환 실패: {e}")
          product_result["failed"] += 1

        # 추가이미지 변환
        if has_additional:
          base_images = list(update_data.get("images", product_images))
          for idx in range(1, len(base_images)):
            try:
              img = await self._download_image(base_images[idx])
              transformed = await self._transform_image_gemini(api_key, model, img, prompt, ref_image)
              new_url = await self._save_image(transformed, base_images[idx])
              base_images[idx] = new_url
              product_result["transformed"] += 1
            except Exception as e:
              logger.error(f"[이미지] {pid} 추가이미지 변환 실패: {e}")
              product_result["failed"] += 1
          update_data["images"] = base_images
        elif product.detail_images:
          # 추가이미지 없으면 상세이미지 변환
          new_details = []
          for img_url in (product.detail_images or []):
            try:
              img = await self._download_image(img_url)
              transformed = await self._transform_image_gemini(api_key, model, img, prompt, ref_image)
              new_url = await self._save_image(transformed, img_url)
              new_details.append(new_url)
              product_result["transformed"] += 1
            except Exception as e:
              logger.error(f"[이미지] {pid} 상세이미지 변환 실패: {e}")
              new_details.append(img_url)
              product_result["failed"] += 1
          update_data["detail_images"] = new_details

      # ── 배경제거 등 기본 모드: scope 그대로 사용 ──
      else:
        use_thumbnail = scope.get("thumbnail", False)
        use_additional = scope.get("additional", False)
        use_detail = scope.get("detail", False)

        # 대표이미지 변환
        if use_thumbnail and product_images:
          try:
            img = await self._download_image(product_images[0])
            transformed = await self._transform_image_gemini(api_key, model, img, prompt, ref_image)
            new_url = await self._save_image(transformed, product_images[0])
            updated_images = list(product_images)
            updated_images[0] = new_url
            update_data["images"] = updated_images
            product_result["transformed"] += 1
          except Exception as e:
            logger.error(f"[이미지] {pid} 대표이미지 변환 실패: {e}")
            product_result["failed"] += 1

        # 추가이미지 변환
        if use_additional and product_images and len(product_images) > 1:
          base_images = list(update_data.get("images", product_images))
          for idx in range(1, len(base_images)):
            try:
              img = await self._download_image(base_images[idx])
              transformed = await self._transform_image_gemini(api_key, model, img, prompt, ref_image)
              new_url = await self._save_image(transformed, base_images[idx])
              base_images[idx] = new_url
              product_result["transformed"] += 1
            except Exception as e:
              logger.error(f"[이미지] {pid} 추가이미지 변환 실패: {e}")
              product_result["failed"] += 1
          update_data["images"] = base_images

        # 상세이미지 변환
        if use_detail and product.detail_images:
          new_details = []
          for img_url in (product.detail_images or []):
            try:
              img = await self._download_image(img_url)
              transformed = await self._transform_image_gemini(api_key, model, img, prompt, ref_image)
              new_url = await self._save_image(transformed, img_url)
              new_details.append(new_url)
              product_result["transformed"] += 1
            except Exception as e:
              logger.error(f"[이미지] {pid} 상세이미지 변환 실패: {e}")
              new_details.append(img_url)
              product_result["failed"] += 1
          update_data["detail_images"] = new_details

      # DB 업데이트
      if update_data:
        try:
          await repo.update_async(pid, **update_data)
        except Exception as e:
          logger.error(f"[이미지] {pid} DB 업데이트 실패: {e}")

      total_transformed += product_result["transformed"]
      total_failed += product_result["failed"]
      results.append(product_result)

    await self.session.commit()
    return {
      "message": f"변환 완료 — 성공 {total_transformed}건, 실패 {total_failed}건",
      "total_transformed": total_transformed,
      "total_failed": total_failed,
      "details": results,
    }

  async def sync_presets_to_r2(self) -> dict[str, Any]:
    """로컬 프리셋 이미지를 R2에 일괄 업로드."""
    import asyncio as _aio
    from functools import partial

    r2 = await self._get_r2_client()
    if not r2:
      return {"success": False, "message": "R2 설정이 없습니다."}

    client, bucket_name, _ = r2
    uploaded: list[str] = []
    failed: list[dict[str, str]] = []

    for key, preset in MODEL_PRESETS.items():
      filename = preset.get("image", "")
      if not filename:
        continue
      local_path = PRESET_IMAGE_DIR / filename
      if not local_path.exists():
        failed.append({"key": key, "reason": "로컬 파일 없음"})
        continue
      try:
        await _aio.to_thread(
          partial(client.upload_fileobj,
            io.BytesIO(local_path.read_bytes()), bucket_name, f"model_presets/{filename}",
            ExtraArgs={"ContentType": "image/png"}),
        )
        uploaded.append(key)
      except Exception as e:
        failed.append({"key": key, "reason": str(e)[:100]})

    return {
      "success": True,
      "message": f"R2 업로드 완료 — 성공 {len(uploaded)}건, 실패 {len(failed)}건",
      "uploaded": uploaded,
      "failed": failed,
    }
