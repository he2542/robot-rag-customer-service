"""Connection and embedding-space compatibility; no knowledge business workflow."""
import atexit
from threading import Lock

import psycopg
from psycopg_pool import ConnectionPool
from src import config

_pool = None
_pool_url = None
_pool_lock = Lock()


def close_pool():
    global _pool, _pool_url
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None
            _pool_url = None


atexit.register(close_pool)


class _PooledConnection:
    """Support both `with connect() as c:` and `c = connect(); c.execute(...); c.close()`."""

    def __init__(self, cm):
        self._cm = cm
        self._conn = None

    def _acquire(self):
        if self._conn is None:
            self._conn = self._cm.__enter__()
        return self._conn

    def __enter__(self):
        return self._acquire()

    def __exit__(self, exc_type, exc, tb):
        if self._conn is not None:
            self._conn = None
            return self._cm.__exit__(exc_type, exc, tb)
        return False

    def close(self):
        self.__exit__(None, None, None)

    def __getattr__(self, name):
        return getattr(self._acquire(), name)


def connect():
    global _pool, _pool_url
    if not config.database_url:
        raise ValueError("DATABASE_URL must be configured")
    conninfo = config.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with _pool_lock:
        if _pool is None or _pool_url != conninfo:
            if _pool is not None:
                _pool.close()
            _pool = ConnectionPool(
                conninfo, min_size=0, max_size=8, timeout=5, open=True,
                kwargs={"connect_timeout": 5, "options": "-c statement_timeout=15000"},
                check=ConnectionPool.check_connection,
            )
            _pool_url = conninfo
        return _PooledConnection(_pool.connection())


def check_embedding_configuration(connection=None):
    if connection is None:
        with connect() as connection:
            return check_embedding_configuration(connection)
    row = connection.execute(
        "SELECT embedding_model, dimensions FROM rag_configuration WHERE id = 1"
    ).fetchone()
    if row != (config.embedding_model_name, config.embedding_dimensions):
        raise ValueError("数据库的嵌入模型或维度与配置不匹配，请先迁移知识库")


def database_ready() -> bool:
    try:
        with connect() as connection:
            check_embedding_configuration(connection)
            connection.execute("SELECT id FROM rag_chunks LIMIT 1")
        return True
    except (psycopg.Error, ValueError):
        return False
