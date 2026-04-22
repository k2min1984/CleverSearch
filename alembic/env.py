"""
########################################################
# Description
# Alembic 환경 설정
# DB 마이그레이션 런타임 환경 구성
# - online/offline 마이그레이션 디렉티브 설정
# - SQLAlchemy 엔진 연결
#
# Modified History
# 강광민 / 2026-03-17 / 최초생성
# 강광민 / 2026-03-23 / 헤더 주석 추가
########################################################
"""
from logging.config import fileConfig
import os
import sys

# [핵심 버그 수정] 윈도우 DB 접속 실패 시 한글 에러(CP949)로 인한 파이썬 강제종료 방지
os.environ["LC_MESSAGES"] = "C"
os.environ["PGCLIENTENCODING"] = "UTF8"

# 프로젝트 최상단 경로를 파이썬 모듈 검색 경로에 추가하여 'app' 모듈을 찾을 수 있게 합니다.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.core.database import Base


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_database_url() -> str:
    # 1순위: 환경변수 DATABASE_URL, 2순위: config.py 자동 조립, 3순위: alembic.ini
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url
    if settings.DATABASE_URL:
        return settings.DATABASE_URL
    return config.get_main_option("sqlalchemy.url")


def run_migrations_offline() -> None:
    url = _get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # [자동화] 스키마가 DB에 존재하지 않으면 자동으로 생성합니다.
        if getattr(settings, "DB_SCHEMA", None):
            from sqlalchemy import text
            connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {settings.DB_SCHEMA}"))
            connection.commit()

        context.configure(
            connection=connection, 
            target_metadata=target_metadata,
            version_table_schema=getattr(settings, "DB_SCHEMA", None)
        )

        with context.begin_transaction():
            if getattr(settings, "DB_SCHEMA", None):
                connection.execute(text(f"SET search_path TO {settings.DB_SCHEMA}"))
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
