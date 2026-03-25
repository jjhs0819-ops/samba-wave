import os
import sys
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool
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
from backend.domain.samba.cs_inquiry.model import *  # noqa: F401,F403
from backend.domain.samba.store_care.model import *  # noqa: F401,F403
from backend.domain.samba.wholesale.model import *  # noqa: F401,F403

config = context.config

# DB URL을 .env에서 설정
db_user = os.getenv("WRITE_DB_USER", "postgres")
db_password = os.getenv("WRITE_DB_PASSWORD", "")
db_host = os.getenv("WRITE_DB_HOST", "localhost")
db_port = os.getenv("WRITE_DB_PORT", "5432")
db_name = os.getenv("WRITE_DB_NAME", "railway")

config.set_main_option(
    "sqlalchemy.url",
    f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}",
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


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
