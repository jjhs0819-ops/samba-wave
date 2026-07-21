"""번장 같은카드 다른셀러 검색 [호스트 실행].

품절 대체용: 키워드로 검색 → saleStatus=SELLING만 + 구매글/일괄/일판 제외.
소싱2 신규발굴에도 사용(min_seller 필터는 상세조회 필요 — 후속).

실행: backend/.venv/Scripts/python.exe samba-tools/ebay_sourcing/search.py "메가 이상해꽃 SAR"
"""

import sys

sys.path.insert(0, __file__.rsplit("ebay_sourcing", 1)[0] + "ebay_sourcing")
from common import BAD_KW, Whale, utf8_stdout  # noqa: E402

utf8_stdout()


def main():
    if len(sys.argv) < 2:
        print("사용법: search.py <키워드> [필수포함단어]")
        return
    kw = sys.argv[1]
    must = sys.argv[2] if len(sys.argv) > 2 else ""
    w = Whale()
    try:
        items = w.search(kw)
        cands = []
        for it in items:
            pid = it.get("pid")
            nm = it.get("name", "") or ""
            if not pid:
                continue
            if any(b in nm.lower() for b in BAD_KW):
                continue
            if must and must not in nm:
                continue
            cands.append((pid, it.get("price"), nm))
        print(f"1차 후보 {len(cands)}건 → saleStatus 확인(SELLING만):")
        ok = []
        for pid, price, nm in cands[:20]:
            p = w.product(str(pid))
            st = p.get("saleStatus")
            if st == "SELLING":
                ok.append((pid, p.get("price"), p.get("imageCount"), nm))
                print(f"  ✅ {pid} | {p.get('price')}원 img{p.get('imageCount')} | {nm[:34]}")
        print(f"\n=== SELLING 최종 {len(ok)}건 ===")
    finally:
        w.close()


if __name__ == "__main__":
    main()
