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
  # Uvicorn — WEB_CONCURRENCY=1로 gunicorn 워커 1개 (환경변수로 설정)
  # --no-dev: 런타임에 dev 패키지 재설치 방지
  echo "Starting production server with Uvicorn (WEB_CONCURRENCY=$WEB_CONCURRENCY)..."
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
