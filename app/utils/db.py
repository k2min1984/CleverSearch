"""
########################################################
# Description
# 멀티 RDB 연결 유틸리티
# - .env의 DB 값을 기준으로 oracle/mysql/postgres 연결 선택
# - 단일/다중 연결 모두 지원
########################################################
"""

from typing import Dict, List, Any

from app.core.config import settings


SUPPORTED_DBS = {"oracle", "mysql", "postgres"}
DB_ALIASES = {
    "postgresql": "postgres",
    "pg": "postgres",
}


def _normalize_db_name(db_name: str) -> str:
    name = (db_name or "").strip().lower()
    return DB_ALIASES.get(name, name)


def get_selected_databases() -> List[str]:
    """
    .env의 DB 값을 파싱해서 활성 DB 목록을 반환합니다.
    예) DB=oracle,mysql,postgres
    """
    raw = (settings.DB or "").strip()
    if not raw:
        return []

    selected: List[str] = []
    for token in raw.split(","):
        normalized = _normalize_db_name(token)
        if normalized in SUPPORTED_DBS and normalized not in selected:
            selected.append(normalized)

    return selected


def _connect_oracle():
    try:
        import oracledb
    except ImportError as exc:
        raise RuntimeError(
            "Oracle 드라이버가 설치되지 않았습니다. `pip install oracledb==2.4.1` 실행 후 재시도하세요."
        ) from exc

    user = settings.ORACLE_USER
    password = settings.ORACLE_PASSWORD
    if not user or not password:
        raise ValueError("Oracle 접속 정보가 부족합니다. ORACLE_USER/ORACLE_PASSWORD를 확인하세요.")

    if settings.ORACLE_DSN:
        dsn = settings.ORACLE_DSN
    else:
        if not settings.ORACLE_SERVICE_NAME:
            raise ValueError("Oracle 접속 정보가 부족합니다. ORACLE_SERVICE_NAME 또는 ORACLE_DSN을 설정하세요.")
        dsn = oracledb.makedsn(
            settings.ORACLE_HOST,
            settings.ORACLE_PORT,
            service_name=settings.ORACLE_SERVICE_NAME,
        )

    return oracledb.connect(user=user, password=password, dsn=dsn)


def _connect_mysql():
    try:
        import pymysql
    except ImportError as exc:
        raise RuntimeError(
            "MySQL 드라이버가 설치되지 않았습니다. `pip install PyMySQL==1.1.1` 실행 후 재시도하세요."
        ) from exc

    if not settings.MYSQL_DATABASE:
        raise ValueError("MySQL 접속 정보가 부족합니다. MYSQL_DATABASE를 설정하세요.")
    if not settings.MYSQL_USER or not settings.MYSQL_PASSWORD:
        raise ValueError("MySQL 접속 정보가 부족합니다. MYSQL_USER/MYSQL_PASSWORD를 확인하세요.")

    return pymysql.connect(
        host=settings.MYSQL_HOST,
        port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER,
        password=settings.MYSQL_PASSWORD,
        database=settings.MYSQL_DATABASE,
        charset="utf8mb4",
        autocommit=False,
    )


def _connect_postgres():
    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError(
            "PostgreSQL 드라이버가 설치되지 않았습니다. `pip install psycopg2-binary==2.9.10` 실행 후 재시도하세요."
        ) from exc

    if not settings.POSTGRES_DATABASE:
        raise ValueError("PostgreSQL 접속 정보가 부족합니다. POSTGRES_DATABASE를 설정하세요.")
    if not settings.POSTGRES_USER or not settings.POSTGRES_PASSWORD:
        raise ValueError("PostgreSQL 접속 정보가 부족합니다. POSTGRES_USER/POSTGRES_PASSWORD를 확인하세요.")

    return psycopg2.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        dbname=settings.POSTGRES_DATABASE,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )


def create_db_connection(db_name: str):
    """
    단일 DB 연결 객체를 생성합니다.
    지원: oracle, mysql, postgres
    """
    normalized = _normalize_db_name(db_name)

    if normalized == "oracle":
        return _connect_oracle()
    if normalized == "mysql":
        return _connect_mysql()
    if normalized == "postgres":
        return _connect_postgres()

    raise ValueError(f"지원하지 않는 DB 타입입니다: {db_name}")


def create_selected_db_connections() -> Dict[str, Any]:
    """
    .env의 DB 설정을 기준으로 단일/다중 DB 연결을 생성합니다.

    Returns:
        Dict[str, Any]: {"oracle": conn, "mysql": conn, "postgres": conn}
    """
    selected = get_selected_databases()
    if not selected:
        return {}

    connections: Dict[str, Any] = {}
    for db_name in selected:
        connections[db_name] = create_db_connection(db_name)

    return connections


def close_db_connections(connections: Dict[str, Any]) -> None:
    """
    create_selected_db_connections()로 생성한 연결들을 안전하게 종료합니다.
    """
    if not connections:
        return

    for _, conn in connections.items():
        try:
            conn.close()
        except Exception:
            pass
