#!/bin/bash
# Cloud Run 수동 배포 스크립트
# 주의: 실제 배포는 GitHub Actions(deploy-cloudrun.yml)를 사용하세요.
# 수동 배포가 필요한 경우 아래 환경변수를 먼저 설정하세요:
#   export WRITE_DB_PASSWORD=<비밀번호>
#   export WRITE_DB_HOST=<호스트>
#   export JWT_SECRET_KEY=<시크릿>

set -euo pipefail

: "${WRITE_DB_PASSWORD:?환경변수 WRITE_DB_PASSWORD를 설정하세요}"
: "${WRITE_DB_HOST:?환경변수 WRITE_DB_HOST를 설정하세요}"
: "${JWT_SECRET_KEY:?환경변수 JWT_SECRET_KEY를 설정하세요}"

gcloud run deploy samba-wave-backend \
  --image asia-northeast3-docker.pkg.dev/glass-sight-452013-n6/samba-wave/backend:latest \
  --region asia-northeast3 \
  --platform managed \
  --port 8080 \
  --memory 1Gi \
  --set-env-vars \
    ENVIRONMENT=production,\
    write_db_user=samba-user,\
    write_db_password="${WRITE_DB_PASSWORD}",\
    write_db_host="${WRITE_DB_HOST}",\
    write_db_port=5432,\
    write_db_name=samba-wave,\
    read_db_user=samba-user,\
    read_db_password="${WRITE_DB_PASSWORD}",\
    read_db_host="${WRITE_DB_HOST}",\
    read_db_port=5432,\
    read_db_name=samba-wave,\
    db_ssl_required=false,\
    jwt_secret_key="${JWT_SECRET_KEY}"
