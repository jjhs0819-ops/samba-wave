"""problems.json(품절) → 같은카드 SELLING 다른셀러 후보 자동탐색 [호스트].

카드번호 있으면 번호로, 없으면 몬명+레어도 토큰 매칭(revive_inactive.bunjang_pick 안전규칙 재사용).
비카드(굿즈/박스/응원봉) 자동 skip → 별도 보고.
"""
import json
import re
import sys

sys.path.insert(0, __file__.rsplit("ebay_sourcing", 1)[0] + "ebay_sourcing")
from common import BAD_KW, Whale, utf8_stdout  # noqa: E402

# 가격이 진짜가 아닌 매물(네고/교환가/제시가) — 2026-08-06 5,000원 트랩 사고로 추가.
# 제목에 콤마·이런 단어 있으면 title price를 신뢰 불가로 보고 후보 제외.
NEGOTIABLE_KW = ["교환", "제시", "네고", "판교"]

utf8_stdout()

NON_CARD_KW = [
    "응원봉", "포카", "유닛", "굿즈", "박스", "부스터팩", "낱개",
    "타부자고",  # 이름만으론 몬X, 나중에 필요시 개별처리
]

RARITY = ["sar", "csr", "hr", "rr", "ur", "sr", "ar"]


def card_no_of(name):
    m = re.search(r"\d{2,3}/[0-9A-Za-z-]{1,6}", name or "")
    return m.group(0).upper() if m else ""


def core_title(name):
    """'포켓몬카드 메가팬텀 sar' → 검색어(카드 접두어/조사 제거)."""
    t = re.sub(r"(포켓몬\s*카드|포켓몬카드)", "", name)
    t = re.sub(r"(팔아요|판매합니다|급처|양도|양도해요|진짜\s*좋아요|A급|한글판).*$", "", t)
    return t.strip()


def main():
    with open("problems.json", "r", encoding="utf-8") as f:
        problems = json.load(f)

    non_card = [p for p in problems if any(k in p["name"] for k in NON_CARD_KW)]
    card_problems = [p for p in problems if p not in non_card]

    print(f"카드 {len(card_problems)}건 / 비카드(수동확인) {len(non_card)}건")

    w = Whale()
    candidates = []
    no_match = []
    try:
        for p in card_problems:
            name = p["name"]
            no = card_no_of(name)
            rarity = next((r for r in RARITY if r in name.lower()), "")
            kw = core_title(name)
            try:
                items = w.search(kw)
            except Exception:
                w.reconnect()
                items = w.search(kw)
            cand = []
            for it in items:
                pid = it.get("pid")
                nm = it.get("name", "") or ""
                if not pid or str(pid) == str(p["pid"]):
                    continue
                if any(b in nm.lower() for b in BAD_KW):
                    continue
                if nm.count(",") >= 1 or any(k in nm for k in NEGOTIABLE_KW):
                    continue
                rar_cnt = len(
                    re.findall(r"(?<![a-z])(sar|csr|hr|rr|ur|sr|ar)(?![a-z])", nm.lower())
                )
                if rar_cnt >= 2 or len(nm) > 40:
                    continue
                if no:
                    numpart = no.split("/")[0]
                    if no not in nm and numpart not in re.findall(r"\d{2,3}", nm):
                        continue
                elif rarity and rarity not in nm.lower():
                    continue
                try:
                    pr = int(it.get("price", 0))
                except Exception:
                    continue
                if pr < 3000 or pr > 300000:
                    continue
                cand.append((pr, pid, nm))
            cand.sort()
            picked = None
            for pr, pid, nm in cand[:5]:
                pp = w.product(str(pid))
                if pp.get("saleStatus") == "SELLING":
                    picked = {
                        "collected_id": p["id"],
                        "old_name": name,
                        "old_pid": p["pid"],
                        "new_pid": pid,
                        "new_name": nm,
                        "new_price": pp.get("price"),
                        "image_url": pp.get("imageUrl"),
                        "image_count": pp.get("imageCount"),
                        "matched_by": "card_no" if no else "name+rarity",
                    }
                    break
            if picked:
                candidates.append(picked)
                print(f"  ✅ {name[:26]} -> {picked['new_pid']} ({picked['new_price']}원) [{picked['matched_by']}]")
            else:
                no_match.append(p)
                print(f"  ❌ {name[:26]} 매칭실패")
    finally:
        w.close()

    with open("candidates.json", "w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=1)
    with open("no_match.json", "w", encoding="utf-8") as f:
        json.dump(no_match + non_card, f, ensure_ascii=False, indent=1)

    print(f"\n=== 후보 {len(candidates)} / 매칭실패 {len(no_match)} / 비카드 {len(non_card)} ===")


if __name__ == "__main__":
    main()
