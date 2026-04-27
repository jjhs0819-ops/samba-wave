#!/usr/bin/env bash
# VM 상태 자동 확인 스크립트
# Claude가 배포 후 사람 개입 없이 VM 상태를 확인하는 용도
# 사용: bash backend/scripts/check_vm.sh [명령어]
#   명령어: logs | status | health | ps | restart-check | all (기본: all)

VM_HOST="api.samba-wave.co.kr"
VM_USER="sbk0674"
SSH_KEY="$HOME/samba-vm-secrets/ssh/deploy_key"
CMD="${1:-all}"

SSH="ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"

# SSH 키 존재 확인
if [[ ! -f "$SSH_KEY" ]]; then
  echo "오류: SSH 키 없음 → $SSH_KEY"
  exit 1
fi

run_vm() {
  $SSH "${VM_USER}@${VM_HOST}" "$@" 2>&1
}

echo "════════════════════════════════════════════"
echo "  VM: $VM_HOST"
echo "  CMD: $CMD"
echo "════════════════════════════════════════════"

case "$CMD" in
  logs)
    echo ""
    echo "[ 백엔드 최근 로그 (50줄) ]"
    run_vm "cd /opt/samba && sudo docker compose logs --tail=50 backend 2>/dev/null || sudo docker logs \$(sudo docker ps -q --filter name=backend) --tail=50 2>/dev/null"
    ;;

  status|ps)
    echo ""
    echo "[ Docker 컨테이너 상태 ]"
    run_vm "sudo docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
    ;;

  health)
    echo ""
    echo "[ Health Check ]"
    # VM 내부에서 직접 호출
    run_vm "curl -s http://localhost:28080/health || curl -s http://localhost:8000/health || echo '응답 없음'"
    echo ""
    echo "[ 외부 Health Check ]"
    curl -s --max-time 5 "https://${VM_HOST}/health" || echo "외부 응답 없음"
    ;;

  error-logs)
    echo ""
    echo "[ 에러 로그 (ERROR/Exception 포함) ]"
    run_vm "cd /opt/samba && sudo docker compose logs --tail=200 backend 2>/dev/null | grep -E 'ERROR|Exception|Traceback|500' | tail -30"
    ;;

  all)
    echo ""
    echo "[ Docker 컨테이너 상태 ]"
    run_vm "sudo docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"

    echo ""
    echo "[ 백엔드 최근 로그 (30줄) ]"
    run_vm "cd /opt/samba && sudo docker compose logs --tail=30 backend 2>/dev/null || sudo docker logs \$(sudo docker ps -q --filter name=backend) --tail=30 2>/dev/null"

    echo ""
    echo "[ 에러 감지 ]"
    ERRORS=$(run_vm "cd /opt/samba && sudo docker compose logs --tail=100 backend 2>/dev/null | grep -c 'ERROR\|Exception\|500' || echo 0")
    if [[ "$ERRORS" -gt 0 ]]; then
      echo "⚠️  최근 로그에서 에러 ${ERRORS}건 감지"
      run_vm "cd /opt/samba && sudo docker compose logs --tail=100 backend 2>/dev/null | grep -E 'ERROR|Exception|500' | tail -10"
    else
      echo "✓ 에러 없음"
    fi
    ;;

  *)
    # 직접 명령어 실행
    echo ""
    echo "[ 직접 실행: $* ]"
    run_vm "$@"
    ;;
esac
