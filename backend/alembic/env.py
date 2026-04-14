import asyncio
import os
import sys
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlmodel import SQLModel

from alembic import context

# .env 로드
load_dotenv()

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Samba 모델 import (autogenerate용)
# user 모델은 JWT 설정 의존성 때문에 제외
from backend.domain.samba.product.model import *  # noqa: F401,F403
from backend.domain.samba.order.model import *  # noqa: F401,F403
from backend.domain.samba.channel.model import *  # noqa: F401,F403
from backend.domain.samba.policy.model import *  # noqa: F401,F403
from backend.domain.samba.collector.model import *  # noqa: F401,F403
from backend.domain.samba.category.model import *  # noqa: F401,F403
from backend.domain.samba.account.model import *  # noqa: F401,F403
from backend.domain.samba.shipment.model import *  # noqa: F401,F403
from backend.domain.samba.forbidden.model import *  # noqa: F401,F403
from backend.domain.samba.contact.model import *  # noqa: F401,F403
from backend.domain.samba.returns.model import *  # noqa: F401,F403
from backend.domain.samba.warroom.model import *  # noqa: F401,F403
from backend.domain.samba.user.model import *  # noqa: F401,F403
from backend.domain.samba.job.model import *  # noqa: F401,F403
from backend.domain.samba.store_care.model import *  # noqa: F401,F403
from backend.domain.samba.wholesale.model import *  # noqa: F401,F403
from backend.domain.samba.sourcing_account.model import *  # noqa: F401,F403

config = context.config

# DB URL을 .env에서 설정
db_user = os.getenv("WRITE_DB_USER") or os.getenv("write_db_user", "postgres")
db_password = os.getenv("WRITE_DB_PASSWORD") or os.getenv("write_db_password", "")
db_host = os.getenv("WRITE_DB_HOST") or os.getenv("write_db_host", "localhost")
db_port = os.getenv("WRITE_DB_PORT") or os.getenv("write_db_port", "5432")
db_name = os.getenv("WRITE_DB_NAME") or os.getenv("write_db_name", "samba_wave")

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

# Cloud SQL Unix 소켓 경로 감지 (/cloudsql/...)
if db_host.startswith("/"):
    config.set_main_option(
        "sqlalchemy.url",
        f"postgresql+asyncpg://{db_user}:{db_password}@/{db_name}?host={db_host}",
    )
else:
    config.set_main_option(
        "sqlalchemy.url",
        f"postgresql+asyncpg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}",
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
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
