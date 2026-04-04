"""CLIP ViT-B-32 모델을 ONNX로 변환 + 텍스트 임베딩 사전 계산.

Docker 멀티스테이지 빌드의 1단계에서 실행된다.
결과물: /clip_onnx/visual.onnx, /clip_onnx/text_features.npy, /clip_onnx/meta.json
"""

import json
import os

import numpy as np
import open_clip
import torch

OUTPUT_DIR = os.environ.get("CLIP_EXPORT_DIR", "/clip_onnx")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── 라벨 정의 (image_filter_service.py와 동일) ──
PRODUCT_LABELS = [
    "a product photo on a plain white or solid color background, no person visible",
    "a close-up detail shot of a product without any human body",
    "a product laid flat on a surface, flat lay photography",
    "a product displayed on a hanger or mannequin without real human",
    "shoes photographed from multiple angles on plain background",
    "a sole or bottom view of shoes on plain background",
]
OTHER_LABELS = [
    "a person wearing or modeling clothes or shoes",
    "human body parts visible such as feet legs hands arms or torso",
    "a lifestyle or outdoor photoshoot with a person",
    "a model standing and posing in clothing on plain background",
    "a full body shot of a person wearing fashion items",
    "a text banner, promotional graphic, or advertisement image",
    "a size chart, specification table, or measurement guide",
    "a brand logo or decorative graphic design",
]

print("[export] CLIP ViT-B-32 로드 중...")
model, _, preprocess = open_clip.create_model_and_transforms(
    "ViT-B-32", pretrained="laion2b_s34b_b79k"
)
tokenizer = open_clip.get_tokenizer("ViT-B-32")
model.eval()

# ── 1. 텍스트 임베딩 사전 계산 ──
print("[export] 텍스트 임베딩 계산 중...")
all_labels = PRODUCT_LABELS + OTHER_LABELS
text_tokens = tokenizer(all_labels)
with torch.no_grad():
    text_features = model.encode_text(text_tokens)
    text_features /= text_features.norm(dim=-1, keepdim=True)

np.save(
    os.path.join(OUTPUT_DIR, "text_features.npy"),
    text_features.cpu().numpy().astype(np.float32),
)

# ── 2. 비주얼 인코더 ONNX 변환 ──
print("[export] 비주얼 인코더 ONNX 변환 중...")
dummy_input = torch.randn(1, 3, 224, 224)


# encode_image 래퍼
class VisualEncoder(torch.nn.Module):
    def __init__(self, clip_model):
        super().__init__()
        self.visual = clip_model.visual

    def forward(self, x):
        features = self.visual(x)
        # L2 정규화
        return features / features.norm(dim=-1, keepdim=True)


visual_encoder = VisualEncoder(model)
visual_encoder.eval()

onnx_path = os.path.join(OUTPUT_DIR, "visual.onnx")
torch.onnx.export(
    visual_encoder,
    dummy_input,
    onnx_path,
    input_names=["pixel_values"],
    output_names=["image_features"],
    dynamic_axes={"pixel_values": {0: "batch"}, "image_features": {0: "batch"}},
    opset_version=17,
)

# ── 3. 메타데이터 저장 ──
meta = {
    "model": "ViT-B-32",
    "pretrained": "laion2b_s34b_b79k",
    "image_size": 224,
    "mean": [0.48145466, 0.4578275, 0.40821073],
    "std": [0.26862954, 0.26130258, 0.27577711],
    "n_product_labels": len(PRODUCT_LABELS),
    "n_other_labels": len(OTHER_LABELS),
}
with open(os.path.join(OUTPUT_DIR, "meta.json"), "w") as f:
    json.dump(meta, f, indent=2)

# 파일 크기 확인
onnx_size = os.path.getsize(onnx_path) / 1024 / 1024
print(f"[export] 완료 — visual.onnx: {onnx_size:.1f}MB")
print(f"[export] 출력 경로: {OUTPUT_DIR}")
