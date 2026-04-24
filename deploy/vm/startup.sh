#!/bin/bash
# GCE VM startup script — 최초 부팅 시 1회 실행되는 초기화 스크립트
# VM 생성 시 metadata.startup-script 로 등록한다.
#
# 실행 내용:
# - Docker + Docker Compose 설치
# - /opt/samba 디렉토리 준비
# - 필수 파일 체크 (없으면 로그만 남기고 대기)
# - systemd 서비스 등록 (재부팅 시 자동 기동)

set -e
exec > >(tee /var/log/samba-startup.log) 2>&1
echo "[$(date)] Samba VM startup begin"

# 1. Docker 설치 (우분투 24.04 기준)
if ! command -v docker &>/dev/null; then
    echo "Installing Docker..."
    apt-get update
    apt-get install -y ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable docker
fi

# 2. Samba 작업 디렉토리
mkdir -p /opt/samba
chown -R ubuntu:ubuntu /opt/samba

# 3. gcloud CLI (이미지 pull용 Artifact Registry 인증)
if ! command -v gcloud &>/dev/null; then
    echo "Installing gcloud..."
    curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
    echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" > /etc/apt/sources.list.d/google-cloud-sdk.list
    apt-get update
    apt-get install -y google-cloud-cli
fi

# 4. Artifact Registry 인증 — VM 서비스계정 사용 (워크로드 ID)
gcloud auth configure-docker asia-northeast3-docker.pkg.dev --quiet

# 5. systemd 서비스 등록 (재부팅 시 docker compose 자동 실행)
cat > /etc/systemd/system/samba-stack.service <<'EOF'
[Unit]
Description=Samba Wave Docker Compose stack
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/samba
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable samba-stack.service

# 6. 초기 설정 안내
if [ ! -f /opt/samba/.env ] || [ ! -f /opt/samba/sa-key.json ] || [ ! -f /opt/samba/docker-compose.yml ]; then
    cat > /opt/samba/SETUP_REQUIRED.txt <<'EOF'
VM 초기 세팅 필요:

1. /opt/samba/.env 배치 (scp 또는 GCP 콘솔 SSH로 업로드)
   - WRITE_DB_*, READ_DB_*, API_GATEWAY_KEY, 기타 시크릿

2. /opt/samba/sa-key.json 배치 (Cloud SQL 접근 서비스계정 키)
   - IAM → 서비스 계정 → 키 생성 (JSON)
   - 권한: roles/cloudsql.client

3. /opt/samba/docker-compose.yml + Caddyfile 배치
   - GitHub repo의 deploy/vm/ 내용 복사

4. 시작:
   sudo systemctl start samba-stack
   sudo docker compose logs -f samba-api
EOF
    echo "Initial setup required. See /opt/samba/SETUP_REQUIRED.txt"
else
    echo "All config files present. Starting stack..."
    systemctl start samba-stack.service
fi

# 7. unattended-upgrades (OS 보안 패치 자동)
apt-get install -y unattended-upgrades
echo 'APT::Periodic::Unattended-Upgrade "1";' > /etc/apt/apt.conf.d/20auto-upgrades
echo 'APT::Periodic::Update-Package-Lists "1";' >> /etc/apt/apt.conf.d/20auto-upgrades

echo "[$(date)] Samba VM startup done"
