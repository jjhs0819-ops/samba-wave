# -*- coding: utf-8 -*-
import json
import os

ITEMS = [
    dict(pid="432256", name_ko="포켓몬 TCG 스칼렛 & 바이올렛 강화 확장팩 낙원 드래고나 박스 (30팩/한글판)", name_en="Pokemon TCG Scarlet & Violet Enhanced Expansion Pack Paradise Dragona Box (Pack of 30/Korean Ver.)", price=34000, tier=39, img="45cf8748fd3c168a.jpg"),
    dict(pid="627587", name_ko="포켓몬 TCG 스칼렛 & 바이올렛 강화 확장팩 열풍의 아레나 박스 (30팩/한글판)", name_en="Pokemon TCG Scarlet & Violet Enhanced Expansion Pack Scorching Arena Box (Pack of 30/Korean Ver.)", price=40000, tier=39, img="845dfaa56d494a91.jpg"),
    dict(pid="627595", name_ko="포켓몬 TCG 스칼렛 & 바이올렛 강화 확장팩 나이트원더러 박스 (30팩/한글판)", name_en="Pokemon TCG Scarlet & Violet Enhanced Expansion Pack Night Wanderer Box (Pack of 30/Korean Ver.)", price=33000, tier=39, img="e8f964136dd0e859.jpg"),
    dict(pid="627591", name_ko="포켓몬 TCG 스칼렛 & 바이올렛 확장팩 스텔라미라클 박스 (30팩/한글판)", name_en="Pokemon TCG Scarlet & Violet Expansion Pack Stellar Miracle Box (Pack of 30/Korean Ver.)", price=37000, tier=39, img="f75f4407229051cb.jpg"),
    dict(pid="627607", name_ko="포켓몬 TCG 스칼렛 & 바이올렛 확장팩 미래의 일섬 박스 (30팩/한글판)", name_en="Pokemon TCG Scarlet & Violet Expansion Pack Future Flash Box (Pack of 30/Korean Ver.)", price=38000, tier=39, img="2a405e7cd9c47a99.jpg"),
    dict(pid="432258", name_ko="포켓몬 TCG 스칼렛 & 바이올렛 확장팩 고대의 포효 1박스 (30팩/한글판)", name_en="Pokemon TCG Scarlet & Violet Expansion Pack Paradox Rift 1Box (Pack of 30/Korean Ver.)", price=38000, tier=39, img="1cb4f8089a7f3357.jpg"),
    dict(pid="432257", name_ko="포켓몬 TCG 스칼렛 & 바이올렛 강화 확장팩 변환의 가면 박스 (30팩/한글판)", name_en="Pokemon TCG Scarlet & Violet Enhanced Expansion Pack Twilight Masquerade Box (Pack of 30/Korean Ver.)", price=48000, tier=49, img="102a5e9aa81532ac.jpg"),
    dict(pid="627599", name_ko="포켓몬 TCG 스칼렛 & 바이올렛 강화 확장팩 크림슨헤이즈 박스 (30팩/한글판)", name_en="Pokemon TCG Scarlet & Violet Enhanced Expansion Pack Crimson Haze Box (Pack of 30/Korean Ver.)", price=38000, tier=49, img="df46b2dadfad4f20.jpg"),
    dict(pid="627583", name_ko="포켓몬 TCG 스칼렛 & 바이올렛 확장팩 로켓단의 영광 박스 (30팩/한글판)", name_en="Pokemon TCG Scarlet & Violet Expansion Pack Glory of Team Rocket Box (Pack of 30/Korean Ver.)", price=53000, tier=49, img="7d86f2390cda4d59.jpg"),
    dict(pid="627579", name_ko="포켓몬 TCG 스칼렛 & 바이올렛 확장팩 화이트플레어 박스 (20팩/한글판)", name_en="Pokemon TCG Scarlet & Violet Expansion Pack White Flare Box (Pack of 20/Korean Ver.)", price=49000, tier=49, img="8d038a92031bb0ff.jpg"),
    dict(pid="627575", name_ko="포켓몬 TCG 스칼렛 & 바이올렛 확장팩 블랙볼트 박스 (20팩/한글판)", name_en="Pokemon TCG Scarlet & Violet Expansion Pack Black Volt Box (Pack of 20/Korean Ver.)", price=48000, tier=49, img="d6a3bfc9e4271bbc.jpg"),
    dict(pid="170605", name_ko="포켓몬 TCG 스칼렛 & 바이올렛 확장팩 흑염의 지배자 박스 (30팩/한글판)", name_en="Pokemon TCG Scarlet & Violet Expansion Pack Obsidian Flames Box (Pack of 30/Korean Ver.)", price=77000, tier=69, img="9b8c7f6845fb52bd.jpg"),
    dict(pid="137483", name_ko="포켓몬 TCG 스칼렛 & 바이올렛 확장팩 클레이 버스트 박스 (30팩/한글판)", name_en="Pokemon TCG Scarlet & Violet Expansion Pack Clay Burst Box (Pack of 30/Korean Ver.)", price=54000, tier=69, img="428fefb910d5b883.jpg"),
    dict(pid="122355", name_ko="포켓몬 TCG 스칼렛 & 바이올렛 확장팩 트리플렛비트 박스 (30팩/한글판)", name_en="Pokemon TCG Scarlet & Violet Expansion Pack Tripletbeat Box (Pack of 30/Korean Ver.)", price=68000, tier=69, img="31f8425c87ce89db.jpg"),
]

out_dir = os.path.join(os.path.dirname(__file__), "_gen_json")
os.makedirs(out_dir, exist_ok=True)

manifest = []
for it in ITEMS:
    body = {
        "source_site": "KREAM",
        "site_product_id": it["pid"],
        "name": it["name_ko"],
        "name_en": it["name_en"],
        "original_price": it["price"],
        "sale_price": it["price"],
        "cost": it["price"],
        "images": [f"https://api.samba-wave.co.kr/images/mirror/{it['img']}"],
        "options": [{"name": "기본", "stock": 2}],
        "status": "collected",
    }
    fp = os.path.join(out_dir, f"create_{it['pid']}.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False)
    manifest.append((it["pid"], it["tier"]))

with open(os.path.join(out_dir, "manifest.txt"), "w", encoding="utf-8") as f:
    for pid, tier in manifest:
        f.write(f"{pid}|{tier}\n")

print("done", len(manifest))
