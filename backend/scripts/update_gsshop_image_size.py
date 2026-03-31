"""
GS샵 수집 상품 이미지 URL 사이즈 일괄 변경 스크립트
/250 (250px 썸네일) → /800 (고해상도) 변환
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

DB_URL = os.getenv('DATABASE_WRITE_URL', '')

# postgresql+asyncpg:// → postgresql:// 변환 (psycopg2용)
conn_str = DB_URL.replace('postgresql+asyncpg://', 'postgresql://')


def main():
    conn = psycopg2.connect(conn_str)
    cur = conn.cursor()

    # 대상 건수 확인
    cur.execute("""
        SELECT COUNT(*)
        FROM samba_collected_product
        WHERE source_site = 'GSShop'
          AND images::text LIKE '%%/250%%'
    """)
    count = cur.fetchone()[0]
    print(f"업데이트 대상: {count}건")

    if count == 0:
        print("변경할 데이터가 없습니다.")
        cur.close()
        conn.close()
        return

    # /250 → /800 일괄 교체
    cur.execute("""
        UPDATE samba_collected_product
        SET images = REPLACE(images::text, '/250', '/800')::jsonb
        WHERE source_site = 'GSShop'
          AND images::text LIKE '%%/250%%'
    """)
    updated = cur.rowcount
    conn.commit()
    print(f"완료: {updated}건 업데이트")

    # 검증
    cur.execute("""
        SELECT id, images
        FROM samba_collected_product
        WHERE source_site = 'GSShop'
        LIMIT 3
    """)
    for row in cur.fetchall():
        print(f"  ID={row[0]}: {str(row[1])[:120]}...")

    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
