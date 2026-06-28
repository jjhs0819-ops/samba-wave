# 로컬 이전 — Phase A (집PC 로컬 스택 검증)

GCP 안 건드리고 집PC `localhost` 에서 백엔드 + 로컬 Postgres 를 띄워 데이터/기능을 검증한다.
백그라운드 워커는 전면 비활성(`DISABLE_BACKGROUND_WORKERS=1`)이라 **라이브 마켓/EMS/스크래핑 무영향**.

## 0. 준비

```bash
cd deploy/local
cp local.env.example local.env
# local.env 편집: LOCAL_DB_PASSWORD 등 + prod .env 시크릿(JWT 등) 채우기
```

`local.env` 는 절대 커밋 금지(.gitignore 등록됨).

> **중요**: 모든 compose 명령에 `--env-file local.env` 를 붙인다.
> (compose 변수 치환 `${LOCAL_DB_PASSWORD}` 는 env_file 이 아니라 `--env-file` 에서 읽음)
> 예: `docker compose --env-file local.env -f docker-compose.local.yml up -d`

## 1. 로컬 Postgres 기동

```bash
docker compose -f docker-compose.local.yml up -d postgres
docker compose -f docker-compose.local.yml ps   # healthy 확인
```

## 2. 프로덕션 데이터 덤프 (Cloud SQL → 파일)

VM 에서 cloud-sql-proxy 경유로 덤프 후 집PC로 내려받는다.

```bash
# (집PC) VM 에 접속해 덤프 생성 — postgres:16 일회성 컨테이너가 cloud-sql-proxy 로 접속
ssh -i ~/samba-vm-secrets/ssh/deploy_key sbk0674@api.samba-wave.co.kr '
  set -a; sudo cat /opt/samba/.env > /tmp/dbenv; source /tmp/dbenv; set +a
  sudo docker run --rm --network samba_samba-net \
    -e PGPASSWORD="$WRITE_DB_PASSWORD" \
    postgres:16-alpine \
    pg_dump -h cloud-sql-proxy -p 5432 -U "$WRITE_DB_USER" -d "$WRITE_DB_NAME" \
    --no-owner --no-privileges -Fc > /tmp/samba.dump
  ls -lh /tmp/samba.dump
'
# 집PC로 내려받기 (DB 크기에 따라 수분~수십분)
scp -i ~/samba-vm-secrets/ssh/deploy_key sbk0674@api.samba-wave.co.kr:/tmp/samba.dump ./samba.dump
```

> network 이름은 `docker network ls | grep samba` 로 확인(보통 `samba_samba-net`).

## 3. 로컬 Postgres 로 복원

```bash
docker compose -f docker-compose.local.yml cp ./samba.dump postgres:/tmp/samba.dump
docker compose -f docker-compose.local.yml exec postgres \
  pg_restore -U samba -d samba --no-owner --no-privileges --clean --if-exists /tmp/samba.dump
```

## 4. 백엔드 기동 + 검증

```bash
docker compose -f docker-compose.local.yml up -d --build samba-api
docker compose -f docker-compose.local.yml logs -f samba-api   # 기동 로그 확인
```

기동 로그 체크포인트:
- alembic 마이그레이션 `upgrade head` 가 no-op(이미 최신)인지
- `DISABLE_BACKGROUND_WORKERS=1` 경고 — 백그라운드 미가동 확인(정상)
- DB 연결 정상

검증:
```bash
curl -s http://localhost:8080/api/v1/health
# 상품 수 등 데이터 검증 (samba_auth 필요 엔드포인트는 토큰 필요)
docker compose -f docker-compose.local.yml exec postgres \
  psql -U samba -d samba -c "SELECT count(*) FROM samba_collected_product;"
```

## 다음 (Phase B~E)

- B: WireGuard 터널 (e2-micro ↔ 집PC)
- C: EMS(`playauto-api.playauto.co.kr`) 아웃바운드를 정적IP로 라우팅
- D: 인바운드 컷오버 + Cloud SQL 중지 + VM 다운사이즈
- E: 백업 cron(pg_dump→R2) + 절전끄기 + 부팅 자동기동

⚠️ Phase D 컷오버 전까지 `DISABLE_BACKGROUND_WORKERS=1` 유지 — 두 곳(GCP+집)에서 동시에 워커 돌면 이중 전송.
