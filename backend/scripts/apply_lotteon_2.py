"""LOTTEON batch2."""

import asyncio
import asyncpg
import json
from backend.core.config import settings

D = {
    "cm_01KQV73T8X13KSSR5CDKV52N7B": {
        "11st": "남성의류 > 정장/슈트 > 정장재킷",
        "auction": "남성의류 > 정장 > 정장자켓",
        "coupang": "패션의류잡화 > 남성패션 > 남성의류 > 재킷 > 남성 정장재킷",
        "gmarket": "남성의류 > 정장 > 정장자켓",
        "lotteon": "남성의류 > 정장 > 정장재킷",
        "smartstore": "패션의류 > 남성의류 > 정장세트",
        "ssg": "신세계몰메인매장 > 남성패션 > 정장/수트 > 정장자켓",
    },
    "cm_01KQV694E672MNA1NREHS4V3N4": {
        "auction": "남성의류 > 정장 > 정장팬츠",
        "gmarket": "남성의류 > 정장 > 정장바지",
        "lotteon": "남성의류 > 정장 > 정장바지",
    },
    "cm_01KQV73T9KQ8TXX3C2V3ZN33WC": {
        "gmarket": "브랜드 남성의류 > 팬츠 > 반바지",
    },
    "cm_01KQV694AGZ1XCT2JK84T4GRRZ": {
        "coupang": "패션의류잡화 > 여성패션 > 여성의류 > 청바지 > 여성 반바지",
        "gmarket": "브랜드 캐주얼의류 > 팬츠 > 데님/청바지",
        "smartstore": "패션의류 > 여성의류 > 청바지",
    },
    "cm_01KQV73TABFNKHNRF9RTD69STA": {
        "11st": "여성의류 > 재킷 > 정장재킷",
        "coupang": "패션의류잡화 > 여성패션 > 여성의류 > 재킷 > 여성 정장재킷",
        "smartstore": "패션의류 > 여성의류 > 정장세트",
    },
    "cm_01KQV73TB3D0QP8XYV8PP3D6QS": {
        "smartstore": "패션의류 > 여성의류 > 바지",
    },
    "cm_01KQV694DF9BZT24E98GGFT3V5": {
        "11st": "브랜드 남성의류 > 바지/팬츠 > 슬랙스",
        "auction": "남성의류 > 캐주얼바지 > 슬랙스",
        "gmarket": "남성의류 > 캐주얼바지 > 슬랙스",
        "lotteon": "남성의류 > 바지 > 슬랙스",
    },
    "cm_01KQV694F0T2M9Z5BC1PX2K546": {
        "11st": "여성의류 > 바지/팬츠 > 면팬츠",
        "auction": "브랜드 여성의류 > 팬츠 > 면팬츠",
    },
    "cm_01KQV73TBSEGD8AS23H3NYXSM1": {
        "11st": "여성의류 > 바지/팬츠 > 슬랙스",
        "auction": "여성의류 > 바지 > 슬랙스",
        "gmarket": "여성의류 > 바지/레깅스 > 슬랙스",
        "smartstore": "패션의류 > 여성의류 > 바지",
        "ssg": "신세계몰메인매장 > 명품/수입의류 > 여성 팬츠 > 슬랙스",
    },
    "cm_01KQV6947HM6JGGR01K5FN2BT9": {
        "auction": "남성의류 > 드레스셔츠 > 프린트/체크셔츠",
        "coupang": "패션의류잡화 > 남성패션 > 남성의류 > 남성 캐주얼 셔츠",
        "gmarket": "남성의류 > 캐주얼셔츠 > 체크 셔츠",
        "lotteon": "남성의류 > 캐주얼셔츠 > 체크셔츠",
        "smartstore": "패션의류 > 남성의류 > 셔츠/남방",
    },
    "cm_01KQV6941PHYSS43SFSVM14JRW": {
        "auction": "남성의류 > 캐주얼바지 > 치노팬츠",
        "gmarket": "브랜드 남성의류 > 팬츠 > 면팬츠/치노팬츠",
    },
    "cm_01KQHRSGBESWG17MEHV70BVJ22": {
        "lotteon": "신발 > 여성샌들 > 웨지샌들",
    },
    "cm_01KR5BBX5C0WW2V7NX1QRJ6D61": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 여성신발 > 샌들",
    },
    "cm_01KQV693WJMCK3J5RDM01G6ZDW": {
        "auction": "남성의류 > 캐주얼셔츠 > 솔리드셔츠",
        "coupang": "패션의류잡화 > 남성패션 > 남성의류 > 남성 캐주얼 셔츠",
        "gmarket": "남성의류 > 드레스셔츠 > 솔리드셔츠",
        "lotteon": "남성의류 > 캐주얼셔츠 > 솔리드셔츠",
        "smartstore": "패션의류 > 남성의류 > 셔츠/남방",
    },
    "cm_01KQHRSG8QX127BBV7JVBE0B53": {
        "lotteon": "신발 > 여성샌들 > 슬링백샌들",
    },
    "cm_01KQV693VVZDSQS1638JT0XZNJ": {
        "auction": "남성의류 > 청바지 > 스트레이트핏",
        "coupang": "패션의류잡화 > 남성패션 > 남성의류 > 청바지 > 남성 긴바지",
        "gmarket": "남성의류 > 청바지 > 스트레이트핏",
        "lotteon": "남성의류 > 청바지 > 스트레이트핏",
    },
    "cm_01KQV6942C8EBA9EH6CXNES3MV": {
        "auction": "여성의류 > 청바지 > 스트레이트핏",
        "coupang": "패션의류잡화 > 여성패션 > 여성의류 > 청바지 > 여성 긴바지",
        "gmarket": "여성의류 > 청바지 > 스트레이트핏",
        "lotteon": "여성의류 > 청바지 > 스트레이트핏",
    },
    "cm_01KQV694089CE8P5SQ10WTCF2W": {
        "auction": "남성의류 > 캐주얼셔츠 > 스트라이프셔츠",
        "coupang": "패션의류잡화 > 남성패션 > 남성의류 > 남성 캐주얼 셔츠",
        "gmarket": "남성의류 > 드레스셔츠 > 스트라이프셔츠",
        "lotteon": "남성의류 > 캐주얼셔츠 > 스트라이프셔츠",
        "smartstore": "패션의류 > 남성의류 > 셔츠/남방",
    },
    "cm_01KQHRSG0N2SC2NZBN31ZDRMFY": {
        "11st": "수입명품 > 여성신발 > 로퍼",
    },
    "cm_01KR5BBY9VBT1492EZQB193HNG": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 여성신발 > 플랫/로퍼",
    },
    "cm_01KR5BBX5A34MGTXPKP9ZZWW17": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 여성신발 > 부츠",
    },
    "cm_01KQV73TCJ1GCZSYBGX2SYV4D0": {
        "11st": "남성의류 > 니트/스웨터 > 터틀넥/폴라",
        "auction": "남성의류 > 니트 > 터틀넥/폴라니트",
        "coupang": "패션의류잡화 > 남성패션 > 남성의류 > 스웨터/니트 > 남성 터틀넥",
        "lotteon": "남성의류 > 니트/스웨터 > 터틀넥/폴라니트",
        "smartstore": "패션의류 > 남성의류 > 니트 > 터틀넥",
        "ssg": "신세계몰메인매장 > 남성패션 > 니트/베스트 > 터틀넥니트",
    },
    "cm_01KQV73TD9ZQYWR7ETJWPVSZYB": {
        "11st": "브랜드 남성의류 > 조끼/베스트 > 니트",
        "auction": "브랜드 캐주얼의류 > 니트/가디건 > 가디건/집업/베스트",
        "coupang": "패션의류잡화 > 남성패션 > 남성의류 > 스웨터/니트 > 남성 카라넥",
        "gmarket": "브랜드 캐주얼의류 > 니트/가디건 > 가디건/집업/베스트",
        "lotteon": "남성의류 > 니트/스웨터 > 집업니트",
        "smartstore": "패션의류 > 남성의류 > 니트 > 베스트",
        "ssg": "신세계몰메인매장 > 남성패션 > 니트/베스트 > 베이직니트",
    },
    "cm_01KQV6953VV9RZGBN5NXEMVTQT": {
        "11st": "여성의류 > 조끼/베스트 > 니트 조끼",
        "lotteon": "여성의류 > 가디건/조끼 > 니트조끼",
        "smartstore": "패션의류 > 여성의류 > 니트 > 베스트",
    },
    "cm_01KQV694MKTKRZH24YAVRX4H2Y": {
        "11st": "브랜드 남성의류 > 조끼/베스트 > 니트",
        "auction": "브랜드 남성의류 > 니트/가디건/베스트 > 브이넥니트",
        "coupang": "패션의류잡화 > 남성패션 > 남성의류 > 스웨터/니트 > 남성 카라넥",
        "gmarket": "브랜드 남성의류 > 니트/가디건/베스트 > 브이넥니트",
        "lotteon": "남성의류 > 니트/스웨터 > 브이넥니트",
        "smartstore": "패션의류 > 남성의류 > 니트 > 베스트",
    },
    "cm_01KQV694ZX1T7NP6AYHHKKH753": {
        "11st": "브랜드 여성의류 > 베스트/조끼 > 니트 베스트",
        "auction": "브랜드 남성의류 > 니트/가디건/베스트 > 브이넥니트",
        "coupang": "패션의류잡화 > 여성패션 > 여성의류 > 스웨터/니트 > 여성 카라넥",
        "gmarket": "브랜드 남성의류 > 니트/가디건/베스트 > 브이넥니트",
        "lotteon": "여성의류 > 니트/스웨터 > 브이넥니트",
        "smartstore": "패션의류 > 여성의류 > 니트 > 베스트",
    },
    "cm_01KQV693X92XWNMWVEZDV47C3M": {
        "11st": "브랜드 남성의류 > 조끼/베스트 > 니트",
        "auction": "브랜드 남성의류 > 니트/가디건/베스트 > 라운드넥니트",
        "coupang": "패션의류잡화 > 남성패션 > 남성의류 > 스웨터/니트 > 남성 카라넥",
        "gmarket": "브랜드 남성의류 > 니트/가디건/베스트 > 라운드 니트",
        "lotteon": "남성의류 > 니트/스웨터 > 라운드넥니트",
        "smartstore": "패션의류 > 남성의류 > 니트 > 베스트",
    },
    "cm_01KQV694QJ7TC3WRDSYRFAJJNE": {
        "11st": "브랜드 여성의류 > 베스트/조끼 > 니트 베스트",
        "auction": "브랜드 남성의류 > 니트/가디건/베스트 > 라운드넥니트",
        "coupang": "패션의류잡화 > 여성패션 > 여성의류 > 스웨터/니트 > 여성 카라넥",
        "gmarket": "브랜드 남성의류 > 니트/가디건/베스트 > 라운드 니트",
        "lotteon": "여성의류 > 니트/스웨터 > 라운드넥니트",
        "smartstore": "패션의류 > 여성의류 > 니트 > 베스트",
    },
    "cm_01KQV693V24HZSHZHPXS983625": {
        "11st": "여성가방 > 쇼퍼백 > 쇼퍼백",
        "auction": "가방/잡화 > 여성가방 > 쇼퍼백",
        "coupang": "패션의류잡화 > 여성패션 > 여성잡화 > 가방 > 여성쇼퍼백",
        "gmarket": "브랜드 잡화 > 여성가방 > 쇼퍼백",
        "lotteon": "가방/지갑 > 여성가방 > 쇼퍼백",
    },
    "cm_01KQV69433J08083AFJX7857TT": {
        "auction": "가방/잡화 > 여성가방 > 숄더백",
        "coupang": "패션의류잡화 > 여성패션 > 여성잡화 > 가방 > 여성숄더백",
        "gmarket": "가방/잡화 > 여성가방 > 숄더백",
        "lotteon": "가방/지갑 > 여성가방 > 숄더백",
    },
    "cm_01KQV73TE03P7KECPB63NTMSC7": {
        "11st": "여성가방 > 에코백 > 에코백",
        "auction": "가방/잡화 > 백팩/캐주얼가방 > 캔버스/에코백",
        "coupang": "패션의류잡화 > 여성패션 > 여성잡화 > 가방 > 여성캔버스/에코백",
        "gmarket": "가방/잡화 > 백팩/캐쥬얼가방 > 에코백",
        "lotteon": "가방/지갑 > 여성가방 > 에코백",
        "smartstore": "패션잡화 > 여성가방 > 에코백",
        "ssg": "신세계몰메인매장 > 가방/지갑 > 캐주얼가방 > 에코백",
    },
    "cm_01KQV6945AAW3RGFECDR7CS3N9": {
        "11st": "여성가방 > 클러치백 > 클러치백",
        "auction": "가방/잡화 > 여성가방 > 클러치백",
        "coupang": "패션의류잡화 > 여성패션 > 여성잡화 > 가방 > 여성클러치",
        "gmarket": "가방/잡화 > 여성가방 > 클러치백",
        "lotteon": "가방/지갑 > 여성가방 > 클러치",
    },
    "cm_01KQV6944HMVY2VK317EEW378H": {
        "auction": "가방/잡화 > 여성가방 > 토트백",
        "coupang": "패션의류잡화 > 여성패션 > 여성잡화 > 가방 > 여성토트백",
        "gmarket": "가방/잡화 > 여성가방 > 토트백",
        "lotteon": "가방/지갑 > 여성가방 > 토트백",
    },
    "cm_01KQV694P330T0KHX88E9DCCDX": {
        "11st": "주니어의류 (9~14세) > 남녀공용의류 > 아우터 > 패딩/다운패딩점퍼",
        "auction": "브랜드 남성의류 > 점퍼/코트 > 패딩/다운점퍼",
        "coupang": "패션의류잡화 > 남성패션 > 남성의류 > 점퍼 > 남성 패딩/다운패딩점퍼",
        "gmarket": "브랜드 캐주얼의류 > 자켓/점퍼/코트 > 다운/패딩",
        "lotteon": "브랜드남성의류 > 점퍼/패딩/야상 > 패딩/다운점퍼",
        "smartstore": "패션의류 > 남성의류 > 아우터 > 패딩",
    },
    "cm_01KQV73TEY5BY61BCT0VHED2H9": {
        "auction": "여성의류 > 점퍼/야상/패딩 > 패딩/다운점퍼",
        "coupang": "패션의류잡화 > 여성패션 > 해외직구 > 아우터류 > 여성 패딩/다운",
        "gmarket": "여성의류 > 점퍼/야상/패딩 > 패딩/다운점퍼",
        "lotteon": "여성의류 > 점퍼/패딩/야상 > 패딩/다운점퍼",
        "smartstore": "패션의류 > 여성의류 > 아우터 > 패딩",
        "ssg": "신세계몰메인매장 > 명품/수입의류 > 여성 아우터 > 패딩",
    },
    "cm_01KQV73TFM76787FDR8Y86P7H2": {
        "11st": "남성의류 > 조끼/베스트 > 니트조끼",
        "coupang": "패션의류잡화 > 남성패션 > 남성의류 > 남성 베스트(조끼)",
        "smartstore": "패션의류 > 남성의류 > 니트 > 베스트",
    },
    "cm_01KQV69461YWKPKFWF7TN8EMN4": {
        "auction": "남성의류 > 점퍼/야상/패딩 > 바람막이점퍼",
        "gmarket": "남성의류 > 점퍼/야상/패딩 > 바람막이 점퍼",
        "lotteon": "남성의류 > 점퍼/패딩/야상 > 바람막이점퍼",
        "smartstore": "패션의류 > 남성의류 > 아우터 > 재킷",
    },
    "cm_01KQV694NBXNZZ894PPH90YWP5": {
        "auction": "남성의류 > 점퍼/야상/패딩 > 바람막이점퍼",
        "coupang": "패션의류잡화 > 남성패션 > 남성의류 > 점퍼 > 남성 바람막이 점퍼",
        "gmarket": "남성의류 > 점퍼/야상/패딩 > 바람막이 점퍼",
        "lotteon": "남성의류 > 점퍼/패딩/야상 > 바람막이점퍼",
        "smartstore": "패션의류 > 남성의류 > 아우터 > 재킷",
    },
    "cm_01KQV693ZF9XQ2QGR2YSQQRT3Q": {
        "auction": "남성의류 > 점퍼/야상/패딩 > 후드/집업점퍼",
        "gmarket": "남성의류 > 점퍼/야상/패딩 > 후드/집업점퍼",
        "lotteon": "남성의류 > 점퍼/패딩/야상 > 후드/집업점퍼",
        "smartstore": "패션의류 > 남성의류 > 아우터 > 재킷",
    },
    "cm_01KQV694SXHJBG6AZ77HA4TKAY": {
        "auction": "브랜드 캐주얼의류 > 자켓/점퍼/코트 > 다운/패딩",
        "gmarket": "브랜드 캐주얼의류 > 자켓/점퍼/코트 > 다운/패딩",
        "lotteon": "브랜드여성의류 > 자켓/코트 > 데님점퍼",
        "smartstore": "패션의류 > 여성의류 > 아우터 > 재킷",
    },
    "cm_01KQV73TGD4WPVW1DN9ASB3A88": {
        "auction": "여성의류 > 마담의류 > 자켓/코트/패딩",
        "coupang": "패션의류잡화 > 여성패션 > 여성의류 > 임산부의류 > 아우터 > 임산부 봄가을 코트/트렌치",
        "gmarket": "여성의류 > 마담의류 > 자켓/코트/패딩",
        "lotteon": "브랜드여성의류 > 자켓/코트 > 레인코트",
        "smartstore": "패션의류 > 여성의류 > 아우터 > 레인코트",
        "ssg": "신세계몰메인매장 > 명품/수입의류 > 여성 아우터 > 코트",
    },
}


async def main():
    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        tree_rows = await conn.fetch(
            "SELECT site_name, cat1, cat2 FROM samba_category_tree"
        )
        mv = {}
        for r in tree_rows:
            c1, c2 = r["cat1"], r["cat2"]
            if isinstance(c1, str):
                c1 = json.loads(c1)
            if isinstance(c2, str):
                c2 = json.loads(c2)
            p = set()
            if isinstance(c1, list):
                p.update(x for x in c1 if isinstance(x, str))
            if isinstance(c2, dict):
                p.update(k for k in c2.keys() if isinstance(k, str))
            elif isinstance(c2, list):
                p.update(x for x in c2 if isinstance(x, str))
            mv[r["site_name"]] = p
        rows_u, keys_a, rej = 0, 0, []
        async with conn.transaction():
            for mid, add in D.items():
                rec = await conn.fetchrow(
                    "SELECT target_mappings FROM samba_category_mapping WHERE id=$1",
                    mid,
                )
                if not rec:
                    continue
                tm = rec["target_mappings"]
                if isinstance(tm, str):
                    tm = json.loads(tm)
                if not isinstance(tm, dict):
                    tm = {}
                merged = dict(tm)
                n = 0
                for mk, path in add.items():
                    if isinstance(merged.get(mk), str) and merged[mk].strip():
                        continue
                    if path not in mv.get(mk, set()):
                        rej.append(f"{mid} {mk}: {path}")
                        continue
                    merged[mk] = path
                    n += 1
                if n:
                    await conn.execute(
                        "UPDATE samba_category_mapping SET target_mappings=$1::jsonb, updated_at=NOW() WHERE id=$2",
                        json.dumps(merged, ensure_ascii=False),
                        mid,
                    )
                    rows_u += 1
                    keys_a += n
        print(f"LOTTEON b2: 행 {rows_u}, 키 {keys_a}, 미일치 {len(rej)}")
        if rej:
            for r in rej[:3]:
                print(f"  {r}")
    finally:
        await conn.close()


asyncio.run(main())
