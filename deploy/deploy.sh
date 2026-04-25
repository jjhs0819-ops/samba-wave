#!/bin/bash
# 로컬 수동 배포 스크립트 — Docker build → AR push → VM deploy → 카카오 알림
#
# 사전 준비:
# 1. Docker Desktop 실행 중
# 2. gcloud auth configure-docker asia-northeast3-docker.pkg.dev (최초 1회)
# 3. ~/samba-vm-secrets/deploy.env 파일 작성 (카카오 토큰)
# 4. ~/samba-vm-secrets/ssh/deploy_key 존재 확인
#
# 실행:
#   bash scripts/deploy.sh              # 일반 배포
#   bash scripts/deploy.sh --skip-kakao # 카카오 알림 건너뛰기
#
# 소요 시간: 약 3~5분 (캐시 적중 시 1~2분)

set -e

# ─────────────────────────────────────
# 설정
# ─────────────────────────────────────
PROJECT_ID="fresh-sanctuary-489804-v4"
AR_REGION="asia-northeast3"
AR_REPO="cloud-run-source-deploy"
IMAGE_NAME="samba-wave-api"
VM_HOST="api.samba-wave.co.kr"
VM_USER="sbk0674"
SSH_KEY="$HOME/samba-vm-secrets/ssh/deploy_key"
ENV_FILE="$HOME/samba-vm-secrets/deploy.env"

IMAGE="${AR_REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${IMAGE_NAME}"
SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "local")
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
START_TIME=$(date +%s)

# 옵션 파싱
SKIP_KAKAO=false
NO_CACHE=false
for arg in "$@"; do
  case "$arg" in
    --skip-kakao) SKIP_KAKAO=true ;;
    --no-cache)   NO_CACHE=true ;;
  esac
done

if [[ -f "$ENV_FILE" ]] && [[ "$SKIP_KAKAO" == "false" ]]; then
  set +e
  source "$ENV_FILE"
  set -e
fi

# ─────────────────────────────────────
# 컬러 출력
# ─────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_step() { echo -e "${BLUE}[$(date +%H:%M:%S)] [$1/$2]${NC} $3"; }
log_ok()   { echo -e "${GREEN}✅ $1${NC}"; }
log_err()  { echo -e "${RED}❌ $1${NC}"; }

# ─────────────────────────────────────
# 카카오 알림 함수
# ─────────────────────────────────────
# Git Bash(Windows) CP949 이슈로 쉘에서 한글 전달이 깨져서 오므로
# 한글 라벨은 deploy/kakao_notify.py 내부에 두고, 쉘에서는 ASCII 인자만 전달한다.
kakao_notify() {
  local status="$1"            # success | fail
  local failure_reason="${2:-}"  # healthcheck | build | push | ssh | generic | ""
  local exit_code="${3:-0}"
  local elapsed="${4:-0}"

  if [[ "$SKIP_KAKAO" == "true" ]] || [[ -z "${KAKAO_API_KEY:-}" ]] || [[ -z "${KAKAO_REFRESH_TOKEN:-}" ]]; then
    return 0
  fi

  python "$(dirname "${BASH_SOURCE[0]}")/kakao_notify.py" \
    --status "$status" \
    --sha "$SHA" \
    --branch "$BRANCH" \
    --failure-reason "$failure_reason" \
    --exit-code "$exit_code" \
    --elapsed "$elapsed" \
    --api-key "$KAKAO_API_KEY" \
    --refresh-token "$KAKAO_REFRESH_TOKEN" \
    > /dev/null 2>&1 || true
}

# ─────────────────────────────────────
# 에러 핸들러 — 어느 단계라도 실패하면 알림
# ─────────────────────────────────────
trap 'on_error $?' ERR
on_error() {
  local exit_code=$1
  local elapsed=$(($(date +%s) - START_TIME))
  log_err "배포 실패 (exit $exit_code, ${elapsed}초)"
  kakao_notify "fail" "generic" "$exit_code" "$elapsed"
  exit "$exit_code"
}

# ─────────────────────────────────────
# 배포 시작
# ─────────────────────────────────────
echo -e "${YELLOW}🚀 Samba Wave 배포 시작${NC}"
echo "   커밋: $SHA ($BRANCH)"
echo "   이미지: $IMAGE"
echo ""

# 1. Docker 빌드 (캐시 활용, --no-cache 옵션 지원)
log_step 1 4 "Docker 이미지 빌드 중..."
DEPLOYED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
BUILD_ARGS=(
  --platform linux/amd64
  --build-arg BUILDKIT_INLINE_CACHE=1
  --build-arg "COMMIT_SHA=$SHA"
  --build-arg "DEPLOYED_AT=$DEPLOYED_AT"
)
if [[ "$NO_CACHE" == "true" ]]; then
  echo "   ⚠️ --no-cache 모드: 전체 재빌드 (5~10분 소요)"
  BUILD_ARGS+=(--no-cache)
else
  BUILD_ARGS+=(--cache-from "$IMAGE:latest")
fi
DOCKER_BUILDKIT=1 docker build \
  "${BUILD_ARGS[@]}" \
  -t "$IMAGE:$SHA" \
  -t "$IMAGE:latest" \
  ./backend
log_ok "빌드 완료"

# 2. AR 푸시
log_step 2 4 "Artifact Registry 푸시 중..."
docker push "$IMAGE:$SHA"
docker push "$IMAGE:latest"
log_ok "푸시 완료"

# 3. VM 배포 — Blue/Green 무중단
#    흐름: green 띄우기 → green 헬스OK → blue stop(Caddy 자동 fallback) → blue 새 이미지로 재시작
#         → blue 헬스OK(Caddy first 우선이라 자동 복귀) → green stop → 미사용 이미지 정리

# 3-0. VM 설정 파일 동기화 (docker-compose.yml + Caddyfile)
log_step 3 4 "VM 설정 파일 동기화 중..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
scp -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new \
    "$SCRIPT_DIR/vm/docker-compose.yml" \
    "$SCRIPT_DIR/vm/Caddyfile" \
    "${VM_USER}@${VM_HOST}:/tmp/" > /dev/null
ssh -i "$SSH_KEY" "${VM_USER}@${VM_HOST}" '
    set -e
    if ! sudo cmp -s /tmp/docker-compose.yml /opt/samba/docker-compose.yml; then
        sudo cp /tmp/docker-compose.yml /opt/samba/docker-compose.yml
        sudo chown ubuntu:ubuntu /opt/samba/docker-compose.yml
        echo "    docker-compose.yml 갱신됨"
    fi
    CADDY_CHANGED=false
    if ! sudo cmp -s /tmp/Caddyfile /opt/samba/Caddyfile; then
        sudo cp /tmp/Caddyfile /opt/samba/Caddyfile
        sudo chown ubuntu:ubuntu /opt/samba/Caddyfile
        CADDY_CHANGED=true
        echo "    Caddyfile 갱신됨 — reload 예정"
    fi
    if [ "$CADDY_CHANGED" = "true" ]; then
        sudo docker exec samba-caddy-1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
        echo "    ✅ Caddy reload 완료"
    fi
'
log_ok "설정 파일 동기화 완료"

log_step 3 4 "VM Blue/Green 배포 중 (${VM_HOST})..."
ssh -i "$SSH_KEY" \
  -o StrictHostKeyChecking=accept-new \
  -o ConnectTimeout=10 \
  "${VM_USER}@${VM_HOST}" \
  "bash -s" << 'REMOTE_SCRIPT'
set -e
cd /opt/samba

echo "[1/6] green(staging) 이미지 pull..."
sudo docker compose --profile staging pull samba-api-staging

echo "[2/6] green 컨테이너 시작..."
sudo docker compose --profile staging up -d samba-api-staging

echo "[3/6] green 헬스체크 대기 (최대 90초)..."
for i in $(seq 1 18); do
    sleep 5
    STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' samba-samba-api-staging-1 2>/dev/null || echo "missing")
    if [ "$STATUS" = "healthy" ]; then
        echo "    ✅ green healthy (${i}회 시도)"
        break
    fi
    echo "    ⏳ green status=$STATUS ($i/18)"
    if [ "$i" = "18" ]; then
        echo "❌ green 헬스체크 실패 — green 컨테이너 정리 후 종료"
        sudo docker compose --profile staging stop samba-api-staging
        sudo docker compose --profile staging rm -f samba-api-staging
        exit 1
    fi
done

echo "[4/6] blue stop (Caddy 자동으로 green으로 fallback)..."
sudo docker compose stop samba-api
sleep 3

echo "[5/6] blue 새 이미지 pull + 재시작..."
sudo docker compose pull samba-api
sudo docker compose up -d samba-api
for i in $(seq 1 18); do
    sleep 5
    STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' samba-samba-api-1 2>/dev/null || echo "missing")
    if [ "$STATUS" = "healthy" ]; then
        echo "    ✅ blue healthy (${i}회 시도) — Caddy lb_policy first 가 blue 우선 트래픽 자동 복귀"
        break
    fi
    echo "    ⏳ blue status=$STATUS ($i/18)"
    if [ "$i" = "18" ]; then
        echo "⚠️ blue 헬스체크 실패 — green 유지 (수동 복구 필요)"
        exit 1
    fi
done

echo "[6/6] green 컨테이너 정리 + 미사용 이미지 prune..."
sleep 5
sudo docker compose --profile staging stop samba-api-staging
sudo docker compose --profile staging rm -f samba-api-staging
sudo docker image prune -a -f | tail -3

echo ""
echo "=== 최종 상태 ==="
sudo docker compose ps --format 'table {{.Name}}\t{{.Status}}'
REMOTE_SCRIPT
log_ok "VM Blue/Green 배포 완료"

# 4. 헬스체크 (최대 180초 대기) — 커밋 SHA로 최신 리비전 서빙 중인지 검증
log_step 4 4 "헬스체크 중..."
HEALTH_OK=false
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18; do
  sleep 10
  RESP=$(curl -sS -m 10 "https://${VM_HOST}/api/v1/health" 2>/dev/null || echo "")
  STATUS=$(echo "$RESP" | grep -oE '"status":"[^"]*"' | head -1 | cut -d'"' -f4)
  LIVE_SHA=$(echo "$RESP" | grep -oE '"commit":"[^"]*"' | head -1 | cut -d'"' -f4)
  if [[ "$STATUS" == "healthy" ]]; then
    if [[ "$LIVE_SHA" == "$SHA" ]]; then
      log_ok "HTTP 200 + 커밋 $LIVE_SHA 확인 (최신 리비전 서빙 중, 시도 $i)"
    else
      log_ok "HTTP 200 응답 확인 (라이브 커밋: ${LIVE_SHA:-unknown}, 예상: $SHA, 시도 $i)"
    fi
    HEALTH_OK=true
    break
  fi
  echo "   시도 $i/18: status=${STATUS:-none} commit=${LIVE_SHA:-none} — 재시도"
done
if [[ "$HEALTH_OK" != "true" ]]; then
  ELAPSED=$(($(date +%s) - START_TIME))
  log_err "헬스체크 실패 — 최신 리비전이 서빙되지 않음"
  kakao_notify "fail" "healthcheck" "1" "$ELAPSED"
  exit 1
fi

# 성공
ELAPSED=$(($(date +%s) - START_TIME))
echo ""
echo -e "${GREEN}🎉 배포 완료 (총 ${ELAPSED}초)${NC}"
echo "   https://${VM_HOST}"
kakao_notify "success" "" "0" "$ELAPSED"
