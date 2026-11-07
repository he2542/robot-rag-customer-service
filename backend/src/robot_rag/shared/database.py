"""Connection and embedding-space compatibility; no knowledge business workflow."""
import psycopg
from robot_rag import config
def connect():
    if not config.database_url:
        raise ValueError("DATABASE_URL must be configured")
    conninfo = config.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    return psycopg.connect(conninfo, connect_timeout=5, options="-c statement_timeout=15000")


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
