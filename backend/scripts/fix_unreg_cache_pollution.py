"""_unreg_cache 자가증식 오염 보정 스크립트.

배경:
  order.py의 _unreg_cache가 동일 (product_id, channel_name) 그룹에서
  과거 잘못 박힌 source_url/product_image를 모든 후속 주문에 전파하는 버그.

오염 시그널:
  같은 channel_name + source_url 조합에 묶인 행이 2건 이상이고,
  product_name이 서로 매우 다양함 (= 한 source_url이 다양한 상품에 매칭됨).

전략:
  (channel_name, source_url) 그룹 중 distinct(product_name) 수가 임계값 이상인
  그룹의 모든 행에 대해 source_url, product_image, source_site를 NULL 처리.
  collected_product_id는 별도 검증 후 처리(이번 스크립트 X).

기본은 DRY RUN. APPLY=1 환경변수일 때만 실제 UPDATE.
"""

import asyncio
import os

import asyncpg

from backend.core.config import settings


# 한 source_url에 묶인 distinct product_name이 이 수를 넘으면 오염으로 본다.
DISTINCT_NAME_THRESHOLD = 3


async def main():
    apply = os.environ.get("APPLY") == "1"
    print(f"[모드] {'APPLY (실제 UPDATE)' if apply else 'DRY-RUN (조회만)'}")
    print(f"[기준] distinct(product_name) >= {DISTINCT_NAME_THRESHOLD}")
    print()

    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        # 1) 오염 그룹 식별
        groups = await conn.fetch(
            """
            SELECT channel_name, source_url,
                   COUNT(*) AS rows_cnt,
                   COUNT(DISTINCT product_name) AS distinct_names,
                   COUNT(DISTINCT product_id) AS distinct_pids
            FROM samba_order
            WHERE source_url IS NOT NULL
              AND channel_name IS NOT NULL
            GROUP BY channel_name, source_url
            HAVING COUNT(DISTINCT product_name) >= $1
            ORDER BY COUNT(*) DESC
            """,
            DISTINCT_NAME_THRESHOLD,
        )
        print(f"[1] 오염 그룹: {len(groups)}개")
        total_rows = 0
        for g in groups[:30]:
            total_rows += g["rows_cnt"]
            print(
                f"    rows={g['rows_cnt']:<5} names={g['distinct_names']:<4} "
                f"pids={g['distinct_pids']:<4} ch={(g['channel_name'] or '')[:30]:<30} "
                f"url={(g['source_url'] or '')[:70]}"
            )
        if len(groups) > 30:
            print(f"    ... 그리고 {len(groups) - 30}개 그룹 더")
        # 전체 영향 행 수 합산
        total_all = sum(g["rows_cnt"] for g in groups)
        print(f"[1] 영향 받는 총 행 수: {total_all:,}건")

        if not apply:
            print()
            print("DRY-RUN 종료. 실행하려면 APPLY=1 환경변수로 다시 실행.")
            return

        # 2) 실제 UPDATE — source_url, product_image, source_site NULL
        # source_site는 _unreg_cache가 직접 채우지 않지만, 같은 경로로 들어왔을 수 있으므로
        # 안전을 위해 source_url을 비우는 행에 한해 source_site도 함께 NULL 처리.
        # collected_product_id는 건드리지 않음(별도 검증).
        print()
        print("[2] UPDATE 실행 중...")
        updated_total = 0
        for g in groups:
            res = await conn.execute(
                """
                UPDATE samba_order
                SET source_url = NULL,
                    product_image = NULL,
                    source_site = NULL
                WHERE channel_name = $1
                  AND source_url = $2
                """,
                g["channel_name"],
                g["source_url"],
            )
            # asyncpg execute returns "UPDATE N"
            try:
                n = int(res.split()[-1])
            except Exception:
                n = 0
            updated_total += n
        print(f"[2] UPDATE 완료: {updated_total:,}건 NULL 처리")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
