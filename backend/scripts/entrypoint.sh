#!/bin/sh

# {backend/entrypoint.sh}
#
# Cloud Run 컨테이너 진입점.
# - production: Cloud SQL 대기 → Emergency schema fixes → alembic upgrade → verify_schema → Gunicorn
# - development: uvicorn --reload
#
# 2026-04-17 사고 이후 조용한 실패 패턴 제거:
#   - alembic 3회 실패 시 exit 1로 Cloud Run이 이전 리비전 유지 (침묵으로 배포 green 사고 재발 방지)

set -e

# Default to development if ENVIRONMENT is not set
if [ -z "$ENVIRONMENT" ]; then
  ENVIRONMENT="development"
fi

# Always load .env file for development
if [ "$ENVIRONMENT" = "development" ]; then
  export $(grep -v '^#' .env | grep -v '^$' | xargs)
fi


echo "Running in $ENVIRONMENT mode"

if [ "$ENVIRONMENT" = "production" ]; then
  # Cloud SQL Auth Proxy 사이드카 대기 — 재시도로 확실히 연결 확인
  echo "Waiting for Cloud SQL proxy..."
  for i in 1 2 3 4 5 6; do
    if uv run python -c "
import asyncio, os
async def check():
    import asyncpg
    host = os.environ.get('WRITE_DB_HOST') or ''
    if not host: return False
    kw = dict(user=os.environ.get('WRITE_DB_USER') or 'postgres', password=os.environ.get('WRITE_DB_PASSWORD') or '', database=os.environ.get('WRITE_DB_NAME') or 'railway')
    if host.startswith('/'): kw['host'] = host
    else: kw['host'] = host; kw['port'] = int(os.environ.get('WRITE_DB_PORT') or 5432)
    conn = await asyncpg.connect(**kw)
    await conn.close()
    return True
r = asyncio.run(check())
exit(0 if r else 1)
" 2>/dev/null; then
      echo "Cloud SQL proxy ready (attempt $i)."
      break
    fi
    echo "Cloud SQL proxy not ready, retrying in 5s... (attempt $i/6)"
    sleep 5
  done

  # Emergency schema fixes — alembic_version=873871a20399 stamp 상태에서 누락된 테이블/컬럼 수동 보완
  # (2026-04-17 사고 이후 stamp-DB 간극 해소용. 신규 누락 항목은 여기 추가)
  echo "Applying emergency schema fixes..."
  uv run python -c "
import asyncio, os, sys
def _env(key):
    return os.environ.get(key) or os.environ.get(key.lower()) or os.environ.get(key.upper()) or ''
async def fix():
    import asyncpg
    host = _env('WRITE_DB_HOST')
    if not host:
        print('WRITE_DB_HOST not set, skip emergency fix'); return
    kw = dict(user=_env('WRITE_DB_USER') or 'postgres', password=_env('WRITE_DB_PASSWORD'), database=_env('WRITE_DB_NAME') or 'railway')
    if host.startswith('/'):
        kw['host'] = host
    else:
        kw['host'] = host; kw['port'] = int(_env('WRITE_DB_PORT') or 5432)
    conn = await asyncpg.connect(**kw)
    try:
        # 배포 시 TooManyConnectionsError 방지 — alembic 실행 전 idle 연결 선제 정리
        terminated = await conn.fetchval(
            'SELECT COUNT(*) FROM pg_stat_activity'
            ' WHERE state = \'idle\' AND datname = current_database()'
            ' AND pid <> pg_backend_pid() AND pg_terminate_backend(pid)'
        )
        print(f'Cleared {terminated} idle connections before alembic.')
        await conn.execute('ALTER TABLE samba_search_filter ADD COLUMN IF NOT EXISTS source_brand_name TEXT')
        await conn.execute('ALTER TABLE samba_market_account DROP COLUMN IF EXISTS sort_order')
        await conn.execute('ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS clm_req_seq TEXT')
        await conn.execute('ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS ord_prd_seq TEXT')
        await conn.execute('ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS exchange_retrieval_status TEXT')
        await conn.execute('ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS exchange_retrieved_at TIMESTAMPTZ')
        await conn.execute('ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS exchange_reship_company TEXT')
        await conn.execute('ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS exchange_reship_tracking TEXT')
        await conn.execute('ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS exchange_delivered_at TIMESTAMPTZ')
        await conn.execute('ALTER TABLE samba_order ADD COLUMN IF NOT EXISTS collected_product_id TEXT')
        await conn.execute('CREATE INDEX IF NOT EXISTS ix_samba_order_collected_product_id ON samba_order (collected_product_id) WHERE collected_product_id IS NOT NULL')
        # samba_search_cache (2b3042f4d3b6 마이그레이션 — stamp로 skip됨, 수동 생성 필요)
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS samba_search_cache (
                id VARCHAR(30) PRIMARY KEY NOT NULL,
                tenant_id VARCHAR(100),
                source_site VARCHAR(50) NOT NULL,
                keyword VARCHAR(200) NOT NULL,
                products JSON,
                ttl_minutes INTEGER NOT NULL DEFAULT 60,
                created_at TIMESTAMPTZ NOT NULL
            )
        ''')
        await conn.execute('CREATE INDEX IF NOT EXISTS ix_samba_search_cache_source_site ON samba_search_cache (source_site)')
        await conn.execute('CREATE INDEX IF NOT EXISTS ix_samba_search_cache_tenant_id ON samba_search_cache (tenant_id)')
        print('Emergency schema fixes applied.')
    finally:
        await conn.close()
asyncio.run(fix())
" || echo "Emergency fix failed (non-fatal)"

  # DB 마이그레이션 — RUN_MIGRATIONS=0 설정 시 스킵 (긴급 롤백/디버깅 전용)
  # 기본값 1 (미설정 포함) → 실행 + 실패 시 exit 1. 스킵해도 verify_schema는 아래에서 실행됨.
  if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    echo "Running database migrations..."
    _MIGRATION_OK=0
    for i in 1 2 3; do
      if uv run alembic upgrade heads; then
        echo "Migrations complete."
        _MIGRATION_OK=1
        break
      else
        echo "Migration attempt $i failed, retrying in 3s..."
        sleep 3
      fi
    done
    if [ "$_MIGRATION_OK" != "1" ]; then
      echo "=========================================================="
      echo "FATAL: 마이그레이션 3회 연속 실패 — 서버 시작 차단"
      echo "  이전 리비전이 계속 서빙되며 이 revision은 교체되지 않음"
      echo "  alembic upgrade heads 로그에서 정확한 원인 확인 후"
      echo "  마이그레이션 파일 수정 or 수동 복구 후 재배포"
      echo "=========================================================="
      exit 1
    fi
  else
    echo "=========================================================="
    echo "⚠️  WARNING: RUN_MIGRATIONS=$RUN_MIGRATIONS → 마이그레이션 스킵됨"
    echo "    긴급 상황(롤백/디버깅) 외 사용 금지"
    echo "    영구 설정 시 스키마 불일치 사고 위험 (2026-04-17 4주 사고 참조)"
    echo "    복구 후 반드시 Cloud Run env에서 RUN_MIGRATIONS 제거할 것"
    echo "=========================================================="
  fi

  # 모델 ↔ DB 스키마 정합성 검증 — 불일치 시 서버 시작 차단
  echo "Verifying schema consistency..."
  if ! uv run python scripts/verify_schema.py; then
    echo "FATAL: 스키마 불일치로 서버 시작을 차단합니다. 이전 리비전이 계속 서빙됩니다."
    exit 1
  fi

  # Gunicorn + Uvicorn worker (--no-dev: 런타임 dev 패키지 재설치 방지)
  echo "Starting production server with Gunicorn (1 worker, uvicorn worker class)..."
  exec uv run --no-dev -m gunicorn -w 1 -k uvicorn.workers.UvicornWorker backend.main:app --bind 0.0.0.0:8080 --timeout 120 --graceful-timeout 600
else
  # Run the development server with Uvicorn and --reload
  echo "Starting development server with Uvicorn..."
  exec uv run -m uvicorn backend.main:app --host 0.0.0.0 --port 28080 --reload
fi

# how to kill
# fuser -k 8000/tcp

disown
