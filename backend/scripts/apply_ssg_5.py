"""SSG batch5."""

import asyncio, asyncpg, json
from backend.core.config import settings

D = {
    "cm_01KR5BCWB4Q71R8HH03N2SNK0M": {
        "ssg": "신세계몰메인매장 > 여성브랜드패션 > 원피스 > 미니원피스"
    },
    "cm_01KR5BCWB7GS8PD3P2T00MD99M": {
        "ssg": "신세계몰메인매장 > 여성브랜드패션 > 스커트 > 미디스커트"
    },
    "cm_01KR5BCWB9N08GD3PQ07FBCGEC": {
        "ssg": "신세계몰메인매장 > 여성브랜드패션 > 원피스 > 미디원피스"
    },
    "cm_01KQV693EHR92V10F2T2YZKWMJ": {
        "auction": "여성의류 > 니트 > 라운드넥니트",
        "gmarket": "여성의류 > 니트 > 라운드넥니트",
    },
    "cm_01KR5BDBCDCYT5N352NKPG5WZ6": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 슈즈용품 > 슈케어용품"
    },
    "cm_01KR5BDCD79KC2PK9BAJ1T0HX4": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠가방 > 백팩"
    },
    "cm_01KR5BDCD90717KS1YXCHXYBQ0": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠모자/잡화 > 스포츠모자"
    },
    "cm_01KR5BDDENY9ASSDKENBC7MBR6": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠모자/잡화 > 스포츠벨트"
    },
    "cm_01KR5BDDEVK295484CWW6P4THG": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠모자/잡화 > 스포츠장갑"
    },
    "cm_01KR5BDGRFFEPRKDZ19TM2DRGY": {
        "ssg": "신세계몰메인매장 > 남성패션 > 니트/베스트 > 카라형니트"
    },
    "cm_01KR5BDNQH562ZGC8BJY5KAS9D": {
        "ssg": "신세계몰메인매장 > 남성패션 > 점퍼/패딩 > 블루종/캐주얼점퍼"
    },
    "cm_01KR5E6C69HB4AY8XQV6B74ES3": {
        "ssg": "신세계몰메인매장 > 남성패션 > 셔츠/남방 > 캐주얼셔츠/남방"
    },
    "cm_01KR5E6C6AJZFA61NPRXADACYS": {
        "ssg": "신세계몰메인매장 > 유아동신발/잡화 > 가방/지갑 > 책가방/백팩"
    },
    "cm_01KR5E6C6BW3NAPH5R09D8F2JB": {
        "ssg": "신세계몰메인매장 > 유아동신발/잡화 > 신발 > 운동화/스니커즈"
    },
    "cm_01KR5E6C6CS4E2S9V6YKHAT70Z": {
        "ssg": "신세계몰메인매장 > 신생아/유아패션 > 바지/레깅스 > 반바지"
    },
    "cm_01KR5E6C6DSPRH1MHQ6672X5E8": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 러닝화/의류"
    },
    "cm_01KR5E6C6EVCC2AWBV8HV1S5NX": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠신발/샌들 > 워킹화"
    },
    "cm_01KR5E6C6EVCC2AWBV8HV1S5NY": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠신발/샌들 > 축구화"
    },
    "cm_01KR5E6C6FBJBHVAV01MX66JB5": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠신발/샌들 > 슬리퍼/쪼리"
    },
    "cm_01KR5E6C6GDST3RQADW8PJY2BR": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠모자/잡화 > 스포츠가방"
    },
    "cm_01KR5E6C6HK2M154CC2XXX323P": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠모자/잡화 > 스포츠모자"
    },
    "cm_01KR5E6C6JYKGWFXDVT9XYPDZK": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠모자/잡화 > 스포츠장갑"
    },
    "cm_01KR5E6C6KD4PWDZ3KHVFKQZZ3": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠모자/잡화 > 스포츠양말/아대"
    },
    "cm_01KR5E6C6MV2VPMQWW7YP4VD0P": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 여성스포츠의류 > 다운/패딩"
    },
    "cm_01KR5E6C6N5KYBYC7KP5SH3EEF": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 남성스포츠의류 > 긴바지"
    },
    "cm_01KR5E6C6PG8KPE6A5PDB096AR": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 남성스포츠의류 > 반바지"
    },
    "cm_01KR5E6C6QBXN7X9HNH5FD56W8": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 남성스포츠의류 > 티셔츠"
    },
    "cm_01KR5E6C6RVFMJVYZSBJBVGEH3": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 여성스포츠의류 > 긴바지"
    },
    "cm_01KR5E6C6SGFECGXEJHWZBJGYB": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 여성스포츠의류 > 티셔츠"
    },
    "cm_01KR6RKVWGT2YAGMY0SS5BDXPY": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 남성스포츠의류 > 스포츠 기능성 웨어"
    },
    "cm_01KR5E6C6TB3NFPF4NV02ERTTF": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 여성스포츠의류 > 스포츠 기능성 웨어"
    },
    "cm_01KR5E6C6TB3NFPF4NV02ERTTG": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 남성스포츠의류 > 바람막이/자켓/점퍼"
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
        print(f"SSG b5: 행 {rows_u}, 키 {keys_a}, 미일치 {len(rej)}")
        if rej:
            for r in rej[:5]:
                print(f"  {r}")
    finally:
        await conn.close()


asyncio.run(main())
