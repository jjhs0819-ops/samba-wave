"""candidates.json 대표이미지 몽타주 생성(육안검증용) [호스트]."""
import json
import math
import urllib.request

from PIL import Image

H = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.bunjang.co.kr/"}


def fetch(url):
    req = urllib.request.Request(url, headers=H)
    with urllib.request.urlopen(req, timeout=10) as r:
        import io

        return Image.open(io.BytesIO(r.read())).convert("RGB")


def main():
    with open("candidates.json", "r", encoding="utf-8") as f:
        cands = json.load(f)

    thumbs = []
    for c in cands:
        tmpl = c.get("image_url") or ""
        url = tmpl.replace("{cnt}", "1").replace("{res}", "600")
        try:
            img = fetch(url)
        except Exception as e:
            print("fail", c["new_pid"], e)
            img = Image.new("RGB", (400, 400), (80, 80, 80))
        img.thumbnail((300, 300))
        thumbs.append((c, img))

    cols = 5
    rows = math.ceil(len(thumbs) / cols)
    cell = 320
    label_h = 60
    canvas = Image.new("RGB", (cols * cell, rows * (cell + label_h)), (20, 20, 20))
    from PIL import ImageDraw

    d = ImageDraw.Draw(canvas)
    for i, (c, img) in enumerate(thumbs):
        x = (i % cols) * cell
        y = (i // cols) * (cell + label_h)
        canvas.paste(img, (x + 10, y + 10))
        old = c["old_name"][:16]
        d.text((x + 5, y + cell - 5), f"#{i} {old}", fill=(255, 255, 0))
        d.text((x + 5, y + cell + 12), f"{c['new_price']}원 {c['matched_by']}", fill=(255, 255, 255))

    canvas.save("montage.jpg", quality=85)
    print("saved montage.jpg", canvas.size)


if __name__ == "__main__":
    main()
