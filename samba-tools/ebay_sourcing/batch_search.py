"""리서치 베스트셀러 기반 ATEEZ 포카 / 포켓몬 카드 후보 대량 수집 [호스트 실행].

번장 검색 → SELLING·비LOT·원가30만↓·이미지있음 필터 → pid/이름/가격 수집.
register 단계 dedup 으로 걸러질 것을 고려해 목표보다 넉넉히 모은다.

출력: scratchpad/cands.json {"ateez":[{bpid,price,name,img}], "pokemon":[...]}

실행: backend/.venv/Scripts/python.exe samba-tools/ebay_sourcing/batch_search.py <out.json>
"""

import json
import re
import sys

sys.path.insert(0, __file__.rsplit("ebay_sourcing", 1)[0] + "ebay_sourcing")
from common import BAD_KW, Whale, utf8_stdout  # noqa: E402

utf8_stdout()

MAX_COST = 300000
MIN_COST = 500
WANT = 150  # 목표 30 + dedup(기등록분) 여유 크게 — 페이지네이션으로 뒤쪽 신규카드 확보
PAGES = 5  # 키워드당 검색 페이지 수 — page0=인기(기등록), 뒤 페이지=덜 유명한 신규

ATEEZ_KW = [
    "에이티즈 골든아워 포토카드",
    "에이티즈 포토카드",
    "ateez 포카",
    "에이티즈 트레카",
    "에이티즈 미공포",
    "에이티즈 골든아워 part.5 포카",
    "에이티즈 골든아워 part.4 포카",
    "에이티즈 골든아워 part.3 포카",
    "에이티즈 the world 포카",
    "에이티즈 bouncy 포카",
    "에이티즈 크레이지폼 포카",
    "에이티즈 limitless 포카",
    "에이티즈 zero fever 포카",
    "에이티즈 팬미팅 포카",
    "에이티즈 시즌그리팅 포카",
    "에이티즈 홍중 포카",
    "에이티즈 성화 포카",
    "에이티즈 윤호 포카",
    "에이티즈 여상 포카",
    "에이티즈 산 포카",
    "에이티즈 민기 포카",
    "에이티즈 우영 포카",
    "에이티즈 종호 포카",
    "에이티즈 위버스 포카",
]
# 이미 등록된 인기카드(리자몽/팬텀/피카츄/잉어킹/냐옹/이상해꽃/지가르데/망나뇽/
# 다크라이) 제외한 '다른 카드'만 — generic 검색은 인기카드 flood라 뺐다.
POKE_KW = [
    "파오젠 ex",
    "무쇠머신 ex",
    "테라파고스 ex",
    "마스카나 ex",
    "라우드본 ex",
    "오거폰 ex",
    "챠데스 ex",
    "루카리오 ex",
    "뮤츠 ex",
    "가브리아스 ex",
    "님피아 ex",
    "리자드 ex",
    "가이오가 ex",
    "루기아 ex",
    "레쿠쟈 ex",
    "삐삐 ex",
    "픽시 ex",
    "잠만보 ex",
    "개굴닌자 ex",
    "그우린차 ex",
    "대여르 ex",
    "우라오스 vmax",
    "자시안 v",
    "리자몽 vstar",
    "뮤 vmax",
    "세레비 ex",
    "파치리스 ex",
    "밤선인 ex",
    "타부자고 ex",
    "드닐 ex",
    "이브이 히어로즈",
    "님피아 vmax",
    "리피아 vstar",
    "글레이시아 vstar",
    "꼬부기 ar",
    "파이리 ar",
    "이상해씨 ar",
    "닌자스피너 sar",
    "인페르노x sr",
    "포푸니라 ex",
    "우롱 ex",
    "안농 ar",
    "장크로 ex",
    # [2026-08-01] 키워드 대폭 확장 — 인기몬 44종이 대부분 등록완료라 신규 확보 위해 추가.
    "이상해꽃 ex",
    "거북왕 ex",
    "갸라도스 ex",
    "한카리아스 ex",
    "칠색조 ex",
    "루기아 v",
    "다크라이 ex",
    "지라치 ex",
    "제크로무 ex",
    "레시라무 ex",
    "큐레무 vmax",
    "이벨타르 ex",
    "제르네아스 ex",
    "솔가레오 ex",
    "루나아라 ex",
    "네크로즈마 ex",
    "펄기아 ex",
    "디아루가 ex",
    "기라티나 ex",
    "아르세우스 ex",
    "그란돈 ex",
    "가이오가 vmax",
    "라이코 ex",
    "스이쿤 ex",
    "메타그로스 ex",
    "밀로틱 ex",
    "글라이온 ex",
    "마기아나 ex",
    "볼케니온 ex",
    "제라오라 ex",
    "루가루간 ex",
    "가랄 파이어 ex",
    "레지에레키 vmax",
    "버섯모 ex",
    "찌리비 ex",
    "펜드라 ex",
    "님피아 sar",
    "에이스번 ex",
    "고릴타 ex",
    "인텔리레온 ex",
    "리엔트 ex",
    "만마드 ex",
    "타부자고 sar",
    "레쿠쟈 vmax",
]


# 포토카드 검색 노이즈(거래글·앨범·디지털) 추가 제외
EXTRA_BAD = [
    "교환",
    "앨범",
    "cdp",
    "다이어리",
    "나눔",
    "포카x",
    "포카 x",
    "빈판",
    "탑로더",
    "슬리브",
    "받아요",
    "찾아요",
    "구해요",
    "택포x",
    # 포켓몬: 등급카드/외국판/뽑기팩/복수장 = 한국 낱장 오표기 방지
    "등급",
    "bgr",
    "brg",
    "gem",
    "북미",
    "일어",
    "일본판",
    "일판",
    "서치",
    "낱팩",
    "서치팩",
    "연번",
    "미개봉",
    "박스",
    "부스터",
    "2장",
    "3장",
    "4장",
    "5장",
    "2연",
    "장세트",
    # 번들/굿즈(단일 포카 아님)
    "포스터",
    "우산",
    "인형",
    "키링",
    "1set",
    "친필",
    "싸인",
    "사인",
    "럭드",
    "유닛포카",
    "단체",
    "올멤",
    "럭키드로우",
]
MUST = {  # 라벨별 이름 필수 포함(최소 하나)
    "A": ["포카", "포토카드", "트레카"],
    "S": ["포카", "포토카드", "트레카"],
    "P": [
        "포켓몬",
        "리자몽",
        "뮤",
        "피카츄",
        "이상해",
        "냐옹",
        "개굴",
        "팬텀",
        "잉어킹",
    ],
}
STRAYKIDS_KW = [
    "스키즈 방찬 포카",
    "스키즈 리노 포카",
    "스키즈 창빈 포카",
    "스키즈 현진 포카",
    "스키즈 한 포카",
    "스키즈 필릭스 포카",
    "스키즈 승민 포카",
    "스키즈 아이엔 포카",
    "스키즈 락스타 포카",
    "스키즈 파이브스타 포카",
    "스키즈 매니악 포카",
    "스키즈 오디너리 포카",
    "스키즈 노이지 포카",
    "스키즈 케이스143 포카",
    "스키즈 소셜패스 포카",
    "스키즈 홀리데이 포카",
    "스키즈 런잇 포카",
    "스키즈 this and that 포카",
    "스트레이키즈 시즌그리팅 포카",
    "스키즈 미공포",
    "스트레이키즈 트레카",
    "스키즈 위버스 포카",
    "스키즈 합범 포카",
    "스키즈 팬미팅 포카",
    "스키즈 방찬 미공포",
    "스키즈 현진 미공포",
    "스키즈 필릭스 미공포",
    "스키즈 한 미공포",
    "스키즈 승민 미공포",
    "스키즈 아이엔 미공포",
    "스키즈 리노 미공포",
    "스키즈 창빈 미공포",
    "스키즈 도미네이트 포카",
    "스키즈 언락 포카",
    "스키즈 카르마 포카",
    "스키즈 스테이 포카",
    "스키즈 애드머 포카",
    "스키즈 컴백쇼 포카",
    "스키즈 팝업 포카",
]
# 복수장 묶음/피규어/덱/굿즈 = 단일 낱장 아님 (한국어 표기 포함 — 2026-07-27 워치·교통카드 오등록 재발)
MULTI_BAD = [
    "및",
    ",",
    "/",
    "&",
    "＆",
    "덱",
    "테라리움",
    "리멘트",
    "피규어",
    "100덱",
    " box",
    "15팩",
    "낱팩",
    "시계",
    "워치",
    "스트랩",
    "watch",
    "정품",
    "빈티지",
    "교통카드",
    "이즐",
    "ezl",
    "ez1",
    "뱃지",
    "배지",
    "텀블러",
    "굿즈",
    "키링",
    "인형",
    "포스터",
    "우산",
    "쿠션",
    "스티커",
    "부채",
]
# 포켓몬 단일 낱장 판별용 레어도 토큰(하나는 있어야 특정 카드로 인정)
RARITY = [
    "sar",
    " ar",
    "ar ",
    " sr",
    "sr ",
    " ur",
    "ur ",
    "rr",
    "vmax",
    "vstar",
    " ex",
    "ex ",
    "gx",
    "프로모",
    "promo",
]
# 특정 포켓몬(이게 없으면 '포켓몬카드 낱장' 뭉치 = 어떤 카드인지 불명 → 제외)
POKE_SPECIFIC = [
    "리자몽",
    "팬텀",
    "냐옹",
    "피카츄",
    "뮤",
    "이상해",
    "개굴",
    "잉어킹",
    "가디안",
    "무장조",
    "망나뇽",
    "지가르데",
    "이벨타르",
    "루카리오",
    "뮤츠",
    "가이오가",
    "close",
    "sar",
    "sr",
    "ar",
    "ur",
    "rr",
]


def _norm(nm: str) -> str:
    return re.sub(r"[^가-힣a-z0-9]", "", (nm or "").lower())


PER_KW = 8  # 키워드당 최대 채택 — 페이지네이션으로 뒤쪽 신규카드까지 넉넉히


def _safe(w, fn_name, *a):
    """WS 타임아웃/끊김에 재접속하며 최대 3회 재시도. 실패 시 None."""
    import time

    for _ in range(3):
        try:
            return getattr(w, fn_name)(*a)
        except Exception:
            try:
                w.reconnect()
            except Exception:
                time.sleep(3)
    return None


def collect(w: Whale, keywords, label):
    seen_pid, seen_name, out = set(), set(), []
    must = MUST[label]
    for kw in keywords:
        if len(out) >= WANT:
            break
        kw_taken = 0
        # 포켓몬: 번장 검색이 fuzzy(인기카드 flood)라, 결과 이름에 이 키워드의
        # 몬 이름이 실제로 있어야 채택 → 검색어 다양성이 유지된다.
        kw_core = kw.split()[0] if label == "P" else ""
        # 여러 페이지 넘겨 뒤쪽(덜 유명한=미등록) 매물까지 긁는다. page0만 보면 인기카드뿐.
        items = []
        for _pg in range(PAGES):
            if kw_taken >= PER_KW or len(out) >= WANT:
                break
            pg = _safe(w, "search", kw, 40, _pg) or []
            if not pg:
                break
            items += pg
        for it in items:
            if len(out) >= WANT or kw_taken >= PER_KW:
                break
            pid = it.get("pid")
            nm = it.get("name", "") or ""
            low = nm.lower()
            if not pid or pid in seen_pid:
                continue
            if any(b in low for b in BAD_KW) or any(b in low for b in EXTRA_BAD):
                continue
            if any(b in low for b in MULTI_BAD):
                continue
            if label == "P":
                if kw_core and kw_core not in nm:  # 검색어 몬이 실제 이름에 있어야
                    continue
                if not any(rt in low for rt in RARITY):  # 레어도 없으면 뭉치/제네릭
                    continue
            elif not any(m in nm for m in must):
                continue
            key = _norm(nm)[:24]
            if key in seen_name:
                continue
            p = _safe(w, "product", str(pid))
            if not p or p.get("_err") or p.get("saleStatus") != "SELLING":
                continue
            price = int(p.get("price") or 0)
            if not (MIN_COST <= price <= MAX_COST):
                continue
            if int(p.get("imageCount") or 0) < 1:
                continue
            seen_pid.add(pid)
            seen_name.add(key)
            kw_taken += 1
            out.append(
                {
                    "bpid": str(pid),
                    "price": price,
                    "name": p.get("name") or nm,
                    "img": int(p.get("imageCount") or 1),
                }
            )
            print(
                f"  [{label}] {len(out):2d} {pid} | {price:,}원 | {(p.get('name') or nm)[:34]}"
            )
    return out


def main():
    out_path = sys.argv[1]
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    # 기존 파일 있으면 유지(한쪽만 갱신 가능)
    prev = {}
    try:
        prev = json.load(open(out_path, encoding="utf-8"))
    except Exception:
        pass
    result = {
        "ateez": prev.get("ateez", []),
        "pokemon": prev.get("pokemon", []),
        "skz": prev.get("skz", []),
    }
    groups = {
        "ateez": (ATEEZ_KW, "A"),
        "pokemon": (POKE_KW, "P"),
        "skz": (STRAYKIDS_KW, "S"),
    }
    w = Whale()
    try:
        for key, (kws, lab) in groups.items():
            if only and key != only:
                continue
            print(f"=== {key.upper()} ===")
            result[key] = collect(w, kws, lab)
    finally:
        w.close()
    json.dump(
        result, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1
    )
    print(
        f"\n수집: ATEEZ {len(result['ateez'])} / 포켓몬 {len(result['pokemon'])} "
        f"/ SKZ {len(result['skz'])} → {out_path}"
    )


if __name__ == "__main__":
    main()
