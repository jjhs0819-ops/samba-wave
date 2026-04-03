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
  # Cloud SQL Auth Proxy 사이드카 대기
  echo "Waiting for Cloud SQL proxy..."
  sleep 5

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

  # Uvicorn 단일 프로세스 — 인메모리 잡 로그 + 워커 중복 실행 방지
  echo "Starting production server with Uvicorn (single process)..."
  exec uv run -m uvicorn backend.main:app --host 0.0.0.0 --port 8080
else
  # Run the development server with Uvicorn and --reload
  echo "Starting development server with Uvicorn..."
  exec uv run -m uvicorn backend.main:app --host 0.0.0.0 --port 28080 --reload
fi

# how to kill
# fuser -k 8000/tcp

disown
# force redeploy 1774848910
