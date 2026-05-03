import asyncio
import importlib
import os
import pkgutil
import sys
from logging.config import fileConfig
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlmodel import SQLModel

from alembic import context

# .env 로드
load_dotenv()

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Samba 모든 도메인 모델 자동 import (autogenerate용)
# 새 도메인 추가 시 이 블록 수정 불필요 — */model.py 자동 감지
import backend.domain.samba as _samba_pkg  # noqa: E402

for _, _modname, _ in pkgutil.walk_packages(
    _samba_pkg.__path__, prefix="backend.domain.samba."
):
    if _modname.endswith(".model"):
        importlib.import_module(_modname)

config = context.config

# DB URL을 .env에서 설정
db_user = os.getenv("WRITE_DB_USER") or os.getenv("write_db_user", "test_user")
db_password = os.getenv("WRITE_DB_PASSWORD") or os.getenv(
    "write_db_password", "test_password"
)
db_host = os.getenv("WRITE_DB_HOST") or os.getenv("write_db_host", "localhost")
db_port = os.getenv("WRITE_DB_PORT") or os.getenv("write_db_port", "5433")
db_name = os.getenv("WRITE_DB_NAME") or os.getenv("write_db_name", "test_little_boy")

# ── 운영 DB 직접 마이그레이션 차단 ──
# Cloud Run(ENVIRONMENT=production)에서는 허용, 로컬 개발 환경에서만 차단
_PRODUCTION_HOSTS = ["/cloudsql/fresh-sanctuary", "/cloudsql/samba-wave-molle"]
_is_production_host = any(p in db_host for p in _PRODUCTION_HOSTS)
_app_env = os.getenv("ENVIRONMENT", "development")
if (
    _is_production_host
    and _app_env != "production"
    and not os.getenv("ALEMBIC_PRODUCTION_CONFIRMED")
):
    raise RuntimeError(
        f"[보안 차단] 로컬 개발 환경에서 운영 DB({db_host})에 직접 마이그레이션이 감지되었습니다. "
        "운영 마이그레이션은 Cloud Run 배포(entrypoint.sh)를 통해서만 실행해야 합니다. "
        "직접 실행이 필요하면: ALEMBIC_PRODUCTION_CONFIRMED=1 alembic upgrade heads"
    )

# user/password URL-encoding — 비밀번호에 '@' 등 특수문자 포함 시 URL 파서가
# 구분자로 오해하는 사고 방지 (2026-04-17: "gemini0674@@" 비밀번호로 4주간 alembic 인증 실패)
# %를 %%로 이스케이프 — alembic의 configparser가 %40 같은 encode 결과를 interpolation 문법으로
# 오해하는 2차 사고 방지 (configparser는 %%를 %로 복원, SQLAlchemy가 최종 %40→@ decode)
db_user_encoded = quote_plus(db_user).replace("%", "%%")
db_password_encoded = quote_plus(db_password or "").replace("%", "%%")

# Cloud SQL Unix 소켓 경로 감지 (/cloudsql/...)
if db_host.startswith("/"):
    config.set_main_option(
        "sqlalchemy.url",
        f"postgresql+asyncpg://{db_user_encoded}:{db_password_encoded}@/{db_name}?host={db_host}",
    )
else:
    config.set_main_option(
        "sqlalchemy.url",
        f"postgresql+asyncpg://{db_user_encoded}:{db_password_encoded}@{db_host}:{db_port}/{db_name}",
    )

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    # 2026-04-28 사고 예방: 마이그레이션이 lock 못 잡으면 30초만에 fail-fast.
    # 무한 대기로 connection pool 도미노 고갈을 막아 deploy.sh가 즉시 실패 감지하고
    # blue 컨테이너 unhealthy로 처리 → staging(green) 유지로 사용자 피해 차단.
    from sqlalchemy import text as _sa_text

    connection.execute(_sa_text("SET lock_timeout = '30s'"))
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
        await connection.commit()
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
