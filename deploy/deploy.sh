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
VM_USER="ubuntu"
SSH_KEY="$HOME/samba-vm-secrets/ssh/deploy_key"
ENV_FILE="$HOME/samba-vm-secrets/deploy.env"

IMAGE="${AR_REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${IMAGE_NAME}"
SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "local")
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
START_TIME=$(date +%s)

# 카카오 토큰 로드 (옵션)
SKIP_KAKAO=false
if [[ "$1" == "--skip-kakao" ]]; then
  SKIP_KAKAO=true
fi

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
kakao_notify() {
  local status="$1"
  local message="$2"
  if [[ "$SKIP_KAKAO" == "true" ]] || [[ -z "${KAKAO_API_KEY:-}" ]] || [[ -z "${KAKAO_REFRESH_TOKEN:-}" ]]; then
    return 0
  fi

  local access_token
  access_token=$(curl -s -X POST https://kauth.kakao.com/oauth/token \
    -d "grant_type=refresh_token" \
    -d "client_id=$KAKAO_API_KEY" \
    -d "refresh_token=$KAKAO_REFRESH_TOKEN" \
    | python -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)

  [[ -z "$access_token" ]] && return 0

  local icon="✅"
  [[ "$status" == "fail" ]] && icon="❌"

  curl -s -X POST https://kapi.kakao.com/v2/api/talk/memo/default/send \
    -H "Authorization: Bearer $access_token" \
    --data-urlencode "template_object={\"object_type\":\"text\",\"text\":\"${icon} 배포 ${status}\n커밋: ${SHA}\n브랜치: ${BRANCH}\n\n${message}\",\"link\":{\"web_url\":\"https://api.samba-wave.co.kr/api/v1/health\"}}" \
    > /dev/null
}

# ─────────────────────────────────────
# 에러 핸들러 — 어느 단계라도 실패하면 알림
# ─────────────────────────────────────
trap 'on_error $?' ERR
on_error() {
  local exit_code=$1
  local elapsed=$(($(date +%s) - START_TIME))
  log_err "배포 실패 (exit $exit_code, ${elapsed}초)"
  kakao_notify "fail" "종료 코드 $exit_code, 소요 ${elapsed}초"
  exit "$exit_code"
}

# ─────────────────────────────────────
# 배포 시작
# ─────────────────────────────────────
echo -e "${YELLOW}🚀 Samba Wave 배포 시작${NC}"
echo "   커밋: $SHA ($BRANCH)"
echo "   이미지: $IMAGE"
echo ""

# 1. Docker 빌드 (캐시 활용)
log_step 1 4 "Docker 이미지 빌드 중..."
DOCKER_BUILDKIT=1 docker build \
  --platform linux/amd64 \
  --cache-from "$IMAGE:latest" \
  --build-arg BUILDKIT_INLINE_CACHE=1 \
  -t "$IMAGE:$SHA" \
  -t "$IMAGE:latest" \
  ./backend
log_ok "빌드 완료"

# 2. AR 푸시
log_step 2 4 "Artifact Registry 푸시 중..."
docker push "$IMAGE:$SHA"
docker push "$IMAGE:latest"
log_ok "푸시 완료"

# 3. VM 배포 (pull + restart)
log_step 3 4 "VM 배포 중 (${VM_HOST})..."
ssh -i "$SSH_KEY" \
  -o StrictHostKeyChecking=accept-new \
  -o ConnectTimeout=10 \
  "${VM_USER}@${VM_HOST}" \
  "cd /opt/samba && sudo docker compose pull samba-api && sudo docker compose up -d samba-api && sudo docker compose ps --format 'table {{.Name}}\t{{.Status}}'"
log_ok "VM 재시작 완료"

# 4. 헬스체크 (최대 60초 대기)
log_step 4 4 "헬스체크 중..."
for i in 1 2 3 4 5 6; do
  sleep 10
  STATUS=$(curl -sS -m 10 -o /dev/null -w "%{http_code}" "https://${VM_HOST}/api/v1/health" || echo 000)
  if [[ "$STATUS" == "200" ]]; then
    log_ok "HTTP 200 응답 확인 (시도 $i)"
    break
  fi
  echo "   시도 $i/6: HTTP $STATUS — 재시도"
  if [[ $i == 6 ]]; then
    log_err "헬스체크 실패 (마지막 응답: HTTP $STATUS)"
    kakao_notify "fail" "헬스체크 HTTP $STATUS"
    exit 1
  fi
done

# 성공
ELAPSED=$(($(date +%s) - START_TIME))
echo ""
echo -e "${GREEN}🎉 배포 완료 (총 ${ELAPSED}초)${NC}"
echo "   https://${VM_HOST}"
kakao_notify "성공" "소요 ${ELAPSED}초"
