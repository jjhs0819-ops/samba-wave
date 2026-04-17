#!/bin/sh

# {backend/entrypoint.sh}

# This script is the entrypoint for the application container.
# It checks the ENVIRONMENT environment variable and runs the appropriate command.

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

  # 누락 컬럼 긴급 패치 (alembic 체인 문제 우회)
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
        print('Emergency schema fixes applied.')
    finally:
        await conn.close()
asyncio.run(fix())
" || echo "Emergency fix failed (non-fatal)"

  # 긴급 우회: alembic_version 테이블 직접 복구 — alembic current/stamp 우회
  # (alembic current 파이프 조건이 로거/exit code 문제로 조용히 실패하는 것을 우회)
  echo "=== [alembic_version] Direct DB repair ==="
  uv run python -c "
import asyncio, os, sys, asyncpg
TARGET = '873871a20399'
async def repair():
    host = os.environ.get('WRITE_DB_HOST') or ''
    if not host:
        print('[alembic_version] skip — WRITE_DB_HOST not set'); return
    kw = dict(
        user=os.environ.get('WRITE_DB_USER') or 'postgres',
        password=os.environ.get('WRITE_DB_PASSWORD') or '',
        database=os.environ.get('WRITE_DB_NAME') or 'railway',
    )
    if host.startswith('/'):
        kw['host'] = host
    else:
        kw['host'] = host
        kw['port'] = int(os.environ.get('WRITE_DB_PORT') or 5432)
    conn = await asyncpg.connect(**kw)
    try:
        await conn.execute('CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)')
        rows = await conn.fetch('SELECT version_num FROM alembic_version ORDER BY 1')
        current = sorted(r[0] for r in rows)
        print(f'[alembic_version] before: {current}')
        if current == [TARGET]:
            print(f'[alembic_version] already {TARGET} — no-op'); return
        if not current or current == ['26dd9b23892a']:
            async with conn.transaction():
                await conn.execute('DELETE FROM alembic_version')
                await conn.execute(\"INSERT INTO alembic_version (version_num) VALUES ('873871a20399')\")
            after = await conn.fetch('SELECT version_num FROM alembic_version ORDER BY 1')
            print(f'[alembic_version] REPAIRED to: {sorted(r[0] for r in after)}')
        else:
            print(f'[alembic_version] UNEXPECTED state: {current} — manual intervention required')
            sys.exit(2)
    finally:
        await conn.close()
asyncio.run(repair())
" || echo '[alembic_version] repair step failed (non-fatal, continuing)'

  # DB 마이그레이션 자동 실행 (최대 3회 재시도)
  echo "Running database migrations..."
  for i in 1 2 3; do
    if uv run alembic upgrade heads; then
      echo "Migrations complete."
      break
    else
      echo "Migration attempt $i failed, retrying in 3s..."
      sleep 3
    fi
  done

  # 모델 ↔ DB 스키마 정합성 검증 — 불일치 시 서버 시작 차단
  echo "Verifying schema consistency..."
  if ! uv run python scripts/verify_schema.py; then
    echo "FATAL: 스키마 불일치로 서버 시작을 차단합니다. 이전 리비전이 계속 서빙됩니다."
    exit 1
  fi

  # Uvicorn 단일 프로세스 — --no-dev: 런타임에 dev 패키지 재설치 방지
  echo "Starting production server with Uvicorn (single process)..."
  exec uv run --no-dev -m uvicorn backend.main:app --host 0.0.0.0 --port 8080
else
  # Run the development server with Uvicorn and --reload
  echo "Starting development server with Uvicorn..."
  exec uv run -m uvicorn backend.main:app --host 0.0.0.0 --port 28080 --reload
fi

# how to kill
# fuser -k 8000/tcp

disown
# force redeploy 1774848910
