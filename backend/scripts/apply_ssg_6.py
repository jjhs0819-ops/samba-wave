"""SSG batch6 (last)."""

import asyncio, asyncpg, json
from backend.core.config import settings

D = {
    "cm_01KR5E6C6V9WDYZSCX13ARGS7Q": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 여성스포츠의류 > 바람막이/자켓/점퍼"
    },
    "cm_01KR5E6C6WHS6GSHC0WDKM1T1F": {
        "ssg": "신세계몰메인매장 > 여성브랜드패션 > 니트/베스트 > 베이직니트"
    },
    "cm_01KQV693QER5VYX4Q7E54SEQY2": {
        "auction": "브랜드 캐주얼의류 > 니트/가디건 > 가디건/집업/베스트",
        "gmarket": "브랜드 캐주얼의류 > 니트/가디건 > 가디건/집업/베스트",
        "lotteon": "브랜드여성의류 > 가디건/조끼 > 집업가디건",
    },
    "cm_01KR5E6C6XSTXE8PY9HF63GYWV": {
        "ssg": "신세계몰메인매장 > 여성브랜드패션 > 가디건 > 오픈형가디건"
    },
    "cm_01KQV693R6A497QFFC3ZFMP2X8": {
        "auction": "브랜드 여성의류 > 티셔츠 > 후드/맨투맨티셔츠",
        "gmarket": "브랜드 여성의류 > 티셔츠 > 맨투맨/후드티셔츠",
        "lotteon": "브랜드여성의류 > 티셔츠/맨투맨 > 후드티/후드집업",
    },
    "cm_01KQV693RYRTGE4PA3SYY5ZGRY": {
        "auction": "브랜드 여성의류 > 티셔츠 > 후드/맨투맨티셔츠",
        "gmarket": "브랜드 여성의류 > 티셔츠 > 맨투맨/후드티셔츠",
        "lotteon": "브랜드여성의류 > 티셔츠/맨투맨 > 후드티/후드집업",
    },
    "cm_01KR5BDDES4EC9997RCGQDSVV6": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠모자/잡화 > 스포츠양말/아대"
    },
    "cm_01KR5BDM1WMW2TW72VYWQ3N4RX": {
        "ssg": "신세계몰메인매장 > 남성패션 > 셔츠/남방 > 캐주얼셔츠/남방"
    },
    "cm_01KR5E6C6YEH50AK074CKFZBQM": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 남성스포츠의류 > 조끼/베스트"
    },
    "cm_01KR5E6C6YEH50AK074CKFZBQN": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 남성스포츠의류 > 트레이닝복세트"
    },
    "cm_01KQV693SNE0GXAKHTRKQKSDZ7": {
        "11st": "브랜드 여성의류 > 티셔츠 > 민소매티셔츠",
        "lotteon": "여성의류 > 티셔츠/맨투맨 > 민소매티셔츠",
    },
    "cm_01KR5BD3GG9HFCCJV4KJP9WT8T": {
        "auction": "남성의류 > 가디건 > 브이넥가디건",
        "lotteon": "남성의류 > 가디건/조끼 > 브이넥가디건",
        "ssg": "신세계몰메인매장 > 남성패션 > 가디건 > 브이넥가디건",
    },
    "cm_01KR5BDSRKEN0W1RSRADPH1B61": {
        "ssg": "신세계몰메인매장 > 여성브랜드패션 > 자켓 > 테일러드자켓"
    },
    "cm_01KR5BCPZHMB26ST9N2DVWRHR5": {
        "lotteon": "남성의류 > 가디건/조끼 > 라운드넥가디건",
        "ssg": "신세계몰메인매장 > 남성패션 > 가디건 > 라운드넥가디건",
    },
    "cm_01KQV693K1MSS5T2JYFWGVQC4P": {
        "auction": "남성의류 > 트레이닝복 > 트레이닝복세트",
        "gmarket": "남성의류 > 트레이닝 > 트레이닝세트",
        "lotteon": "남성의류 > 트레이닝복 > 트레이닝세트",
    },
    "cm_01KR5E6C6ZJ6DBZRDAG4DPDPJ8": {
        "ssg": "신세계몰메인매장 > 남성패션 > 맨투맨/후드/티셔츠 > 반팔티셔츠"
    },
    "cm_01KR5BCXFYMJG9WMRTWS6Z4CAP": {
        "ssg": "신세계몰메인매장 > 신생아/유아패션 > 티셔츠/맨투맨/후드 > 반팔/7부티셔츠"
    },
    "cm_01KR5E6C70MJQ3GQ9HFS5SYD83": {
        "ssg": "신세계몰메인매장 > 남성패션 > 팬츠 > 반바지/7부"
    },
    "cm_01KR5BCXFT1VM796X77E9Z88NX": {
        "ssg": "신세계몰메인매장 > 남성패션 > 팬츠 > 반바지/7부"
    },
    "cm_01KR5BD969Z025VZ663RKSVBGS": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 슈즈용품 > 슈즈ACC"
    },
    "cm_01KR5E6C71VRJD436VFK2GJYGV": {
        "ssg": "신세계몰메인매장 > 모자/장갑/ACC > 선글라스/안경 > 선글라스"
    },
    "cm_01KR5E6C720ZXGXC1KNMRSDCM9": {
        "ssg": "신세계몰메인매장 > 모자/장갑/ACC > 모자 > 볼캡/야구모자"
    },
    "cm_01KR5E6C720ZXGXC1KNMRSDCMA": {
        "ssg": "신세계몰메인매장 > 모자/장갑/ACC > 양말/스타킹/ACC > 양말"
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
        print(f"SSG b6: 행 {rows_u}, 키 {keys_a}, 미일치 {len(rej)}")
        if rej:
            for r in rej[:5]:
                print(f"  {r}")
    finally:
        await conn.close()


asyncio.run(main())
