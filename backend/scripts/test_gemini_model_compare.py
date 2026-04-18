"""
Gemini 모델 비교 테스트: gemini-2.5-flash vs gemini-2.0-flash
사용법: python scripts/test_gemini_model_compare.py <이미지_URL> <GEMINI_API_KEY>
결과: backend/scripts/compare_output/ 에 두 모델 결과 이미지 저장
"""

import asyncio
import base64
import sys
from pathlib import Path

import httpx

PRESET_IMAGE_DIR = Path(__file__).resolve().parent.parent / "backend" / "static" / "model_presets"

MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]

PROMPT = (
    "첫 번째 이미지는 반드시 착용/사용해야 할 상품입니다. "
    "이 상품의 색상, 로고, 패턴, 텍스트, 디자인을 100% 정확하게 재현하세요. "
    "절대로 상품의 디자인을 변경하거나 다른 옷으로 대체하지 마세요. "
    "절대 금지: 원본 이미지에 없는 로고, 텍스트, 스폰서명을 추가하지 마세요. "
    "당신이 알고 있는 브랜드 지식으로 없는 요소를 만들어내지 마세요. 보이는 것만 재현하세요. "
    "\n[중요: 모델 교체 규칙]\n"
    "첫 번째 이미지에 사람/모델이 있다면, 그 사람의 얼굴, 헤어스타일, 피부색, 체형을 모두 무시하세요. "
    "오직 그 사람이 입고 있는 '옷/상품'만 추출하세요. "
    "두 번째 이미지는 새로운 모델의 참조입니다. "
    "생성할 이미지의 모델은 반드시 이 참조 이미지의 얼굴, 헤어스타일, 피부색, 체형을 사용하세요. "
    "원본 상품 이미지에 있던 모델의 외모는 절대 사용하지 마세요. 완전히 다른 사람으로 교체하는 것입니다. "
    "모델은 반드시 백인 서양인(Caucasian)이어야 합니다. "
    "반드시 첫 번째 이미지의 상품을 착용한 사진을 생성해야 합니다. "
    "배경이 캔버스 전체를 빈틈없이 채워야 하며, 흰색 테두리나 여백이 절대 없어야 합니다. "
    "\n패션모델: 22세 백인 서양인 여성 패션모델, 쇄골 아래 길이 스트레이트 브론드 헤어, 날카로운 턱선, 높은 광대뼈, 170cm, 긴 목선, 무표정에 가까운 쿨한 눈빛, 한쪽 어깨를 살짝 앞으로 내민 런웨이 포즈"
)


def _detect_mime(data: bytes) -> str:
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF":
        return "image/webp"
    return "image/jpeg"


async def download_image(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


async def call_gemini(api_key: str, model: str, image_bytes: bytes, ref_bytes: bytes) -> tuple[bytes, dict]:
    parts = [
        {"text": PROMPT},
        {"inline_data": {"mime_type": _detect_mime(image_bytes), "data": base64.b64encode(image_bytes).decode()}},
        {"inline_data": {"mime_type": _detect_mime(ref_bytes), "data": base64.b64encode(ref_bytes).decode()}},
    ]
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    async with httpx.AsyncClient(timeout=120) as client:
        print(f"  [{model}] 요청 중...")
        resp = await client.post(url, json=body, headers={"Content-Type": "application/json"})
        resp.raise_for_status()
        data = resp.json()

    usage = data.get("usageMetadata", {})
    candidates = data.get("candidates", [])
    if not candidates:
        raise ValueError(f"{model}: candidates 없음")

    for part in candidates[0].get("content", {}).get("parts", []):
        if "inlineData" in part:
            return base64.b64decode(part["inlineData"]["data"]), usage

    raise ValueError(f"{model}: 이미지 파트 없음")


async def main(image_url: str, api_key: str):
    out_dir = Path(__file__).resolve().parent / "compare_output"
    out_dir.mkdir(exist_ok=True)

    print(f"상품 이미지 다운로드: {image_url}")
    image_bytes = await download_image(image_url)
    print(f"  크기: {len(image_bytes):,} bytes ({len(image_bytes)//1024}KB)")

    ref_path = PRESET_IMAGE_DIR / "female_v1.png"
    ref_bytes = ref_path.read_bytes()
    print(f"모델 프리셋: {ref_path.name} ({len(ref_bytes)//1024}KB)")

    # 원본 이미지 저장
    with open(out_dir / "00_original.jpg", "wb") as f:
        f.write(image_bytes)

    for model in MODELS:
        try:
            result_bytes, usage = await call_gemini(api_key, model, image_bytes, ref_bytes)
            filename = model.replace(".", "-").replace("/", "-") + ".jpg"
            with open(out_dir / filename, "wb") as f:
                f.write(result_bytes)
            prompt_tok = usage.get("promptTokenCount", "?")
            cand_tok = usage.get("candidatesTokenCount", "?")
            print(f"  [{model}] 완료 — 입력 {prompt_tok}tok / 출력 {cand_tok}tok → {filename}")
        except Exception as e:
            print(f"  [{model}] 실패: {e}")

    print(f"\n결과 저장 위치: {out_dir}")
    print("00_original.jpg  ← 원본 상품 이미지")
    for model in MODELS:
        filename = model.replace(".", "-").replace("/", "-") + ".jpg"
        print(f"{filename}  ← {model} 결과")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("사용법: python scripts/test_gemini_model_compare.py <이미지_URL> <GEMINI_API_KEY>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
