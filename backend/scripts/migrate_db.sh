#!/bin/bash
# ============================================================
# DB 안전 이전 스크립트 (Railway → Google Cloud)
# ============================================================
# 사용법:
#   1. 환경변수 설정 후 실행
#   2. 각 단계별 검증 포함
# ============================================================

set -euo pipefail

# ── 설정 ──
SRC_HOST="${SRC_DB_HOST:?SRC_DB_HOST 설정 필요}"
SRC_PORT="${SRC_DB_PORT:?SRC_DB_PORT 설정 필요}"
SRC_USER="${SRC_DB_USER:?SRC_DB_USER 설정 필요}"
SRC_DB="${SRC_DB_NAME:?SRC_DB_NAME 설정 필요}"

DST_HOST="${DST_DB_HOST:?DST_DB_HOST 설정 필요}"
DST_PORT="${DST_DB_PORT:?DST_DB_PORT 설정 필요}"
DST_USER="${DST_DB_USER:?DST_DB_USER 설정 필요}"
DST_DB="${DST_DB_NAME:?DST_DB_NAME 설정 필요}"

DUMP_DIR="./migration_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$DUMP_DIR"

echo "============================================"
echo " 1단계: 소스(Railway) 스키마+데이터 덤프"
echo "============================================"

# 핵심: --column-inserts 로 컬럼명 포함 INSERT 생성
# 이렇게 하면 대상 DB의 컬럼 순서와 무관하게 정확히 매핑됨
pg_dump \
  -h "$SRC_HOST" -p "$SRC_PORT" -U "$SRC_USER" -d "$SRC_DB" \
  --no-owner --no-privileges \
  --column-inserts \
  --encoding=UTF8 \
  -f "$DUMP_DIR/full_dump_inserts.sql"

echo "  덤프 완료: $DUMP_DIR/full_dump_inserts.sql"

# COPY 형식 덤프도 별도 백업 (빠른 복원용)
pg_dump \
  -h "$SRC_HOST" -p "$SRC_PORT" -U "$SRC_USER" -d "$SRC_DB" \
  --no-owner --no-privileges \
  --encoding=UTF8 \
  -f "$DUMP_DIR/full_dump_copy.sql"

echo "  백업 완료: $DUMP_DIR/full_dump_copy.sql"

echo ""
echo "============================================"
echo " 2단계: 소스 데이터 카운트 기록"
echo "============================================"

PGPASSWORD="$SRC_DB_PASSWORD" psql \
  -h "$SRC_HOST" -p "$SRC_PORT" -U "$SRC_USER" -d "$SRC_DB" \
  -c "
    SELECT 'samba_policy' as tbl, COUNT(*) as cnt, COUNT(tenant_id) as with_tenant FROM samba_policy
    UNION ALL
    SELECT 'samba_search_filter', COUNT(*), COUNT(applied_policy_id) FROM samba_search_filter
    UNION ALL
    SELECT 'samba_collected_product', COUNT(*), 0 FROM samba_collected_product
    UNION ALL
    SELECT 'samba_order', COUNT(*), 0 FROM samba_order
    ORDER BY tbl;
  " | tee "$DUMP_DIR/source_counts.txt"

echo ""
echo "============================================"
echo " 3단계: 대상(GCP) DB에 스키마 생성"
echo "============================================"
echo "  아래 명령으로 alembic 마이그레이션을 먼저 실행하세요:"
echo ""
echo "    # .env에서 DB 접속정보를 GCP로 변경한 후:"
echo "    cd backend && alembic upgrade head"
echo ""
read -p "  alembic 완료 후 Enter 키를 누르세요..."

echo ""
echo "============================================"
echo " 4단계: 데이터 복원"
echo "============================================"

# 스키마 DROP 후 재생성이 아닌, 데이터만 INSERT
# --column-inserts 덤프에서 데이터만 추출
grep "^INSERT INTO" "$DUMP_DIR/full_dump_inserts.sql" > "$DUMP_DIR/data_only.sql"

# SET 문도 필요
echo "SET client_encoding = 'UTF8';" > "$DUMP_DIR/restore.sql"
echo "SET standard_conforming_strings = on;" >> "$DUMP_DIR/restore.sql"
echo "" >> "$DUMP_DIR/restore.sql"

# 테이블 비우기 (FK 순서 고려)
echo "-- 데이터 초기화 (의존 순서)" >> "$DUMP_DIR/restore.sql"
echo "TRUNCATE samba_cs_inquiry, samba_return, samba_order, samba_collected_product, samba_search_filter, samba_category_mapping, samba_policy, samba_detail_template, samba_name_rule, samba_market_account, samba_user CASCADE;" >> "$DUMP_DIR/restore.sql"
echo "" >> "$DUMP_DIR/restore.sql"

cat "$DUMP_DIR/data_only.sql" >> "$DUMP_DIR/restore.sql"

echo "  복원 파일 생성: $DUMP_DIR/restore.sql"
echo ""
echo "  아래 명령으로 복원하세요:"
echo "    PGPASSWORD=\$DST_DB_PASSWORD psql -h \$DST_HOST -p \$DST_PORT -U \$DST_USER -d \$DST_DB -f $DUMP_DIR/restore.sql"
echo ""
read -p "  복원 완료 후 Enter 키를 누르세요..."

echo ""
echo "============================================"
echo " 5단계: 데이터 검증"
echo "============================================"

PGPASSWORD="$DST_DB_PASSWORD" psql \
  -h "$DST_HOST" -p "$DST_PORT" -U "$DST_USER" -d "$DST_DB" \
  -c "
    SELECT 'samba_policy' as tbl, COUNT(*) as cnt, COUNT(tenant_id) as with_tenant FROM samba_policy
    UNION ALL
    SELECT 'samba_search_filter', COUNT(*), COUNT(applied_policy_id) FROM samba_search_filter
    UNION ALL
    SELECT 'samba_collected_product', COUNT(*), 0 FROM samba_collected_product
    UNION ALL
    SELECT 'samba_order', COUNT(*), 0 FROM samba_order
    ORDER BY tbl;
  " | tee "$DUMP_DIR/dest_counts.txt"

echo ""
echo "  소스와 대상 카운트를 비교하세요:"
echo "  diff $DUMP_DIR/source_counts.txt $DUMP_DIR/dest_counts.txt"

echo ""
echo "============================================"
echo " 완료!"
echo "============================================"
