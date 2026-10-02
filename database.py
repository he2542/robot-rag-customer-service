"""Database schema, model compatibility checks and transactional knowledge writes."""

import math
from uuid import NAMESPACE_URL, uuid5

import psycopg
from pgvector.psycopg import Vector, register_vector
from psycopg.types.json import Jsonb

import config_data as config


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


def init_database():
    """Run explicitly at deployment; never overwrite an existing embedding space."""
    with connect() as connection:
        if not connection.execute(
            "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
        ).fetchone():
            raise ValueError("请数据库管理员先启用 pgvector 扩展")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS rag_configuration (
                id integer PRIMARY KEY CHECK (id = 1),
                embedding_model text NOT NULL, dimensions integer NOT NULL
            )
        """)
        connection.execute(
            "INSERT INTO rag_configuration VALUES (1, %s, %s) ON CONFLICT DO NOTHING",
            (config.embedding_model_name, config.embedding_dimensions),
        )
        check_embedding_configuration(connection)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS rag_documents (
                document_hash text PRIMARY KEY, filename text NOT NULL,
                chunk_count integer NOT NULL CHECK (chunk_count > 0),
                created_at timestamptz NOT NULL DEFAULT now()
            )
        """)
        connection.execute(f"""
            CREATE TABLE IF NOT EXISTS rag_chunks (
                id uuid PRIMARY KEY,
                document_hash text NOT NULL REFERENCES rag_documents(document_hash) ON DELETE CASCADE,
                content text NOT NULL,
                embedding vector({config.embedding_dimensions}) NOT NULL,
                metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb
            )
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS rag_chunks_embedding_hnsw
            ON rag_chunks USING hnsw (embedding vector_cosine_ops)
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS rag_chunks_document_hash ON rag_chunks (document_hash)
        """)


def database_ready() -> bool:
    try:
        with connect() as connection:
            check_embedding_configuration(connection)
            connection.execute("SELECT id FROM rag_chunks LIMIT 1")
        return True
    except (psycopg.Error, ValueError):
        return False


def document_exists(document_hash: str) -> bool:
    with connect() as connection:
        check_embedding_configuration(connection)
        return connection.execute(
            "SELECT 1 FROM rag_documents WHERE document_hash = %s", (document_hash,)
        ).fetchone() is not None


def insert_document(document_hash, filename, chunks, vectors, metadata) -> bool:
    if not chunks or len(chunks) != len(vectors):
        raise ValueError("文本片段与向量数量不一致")
    for vector in vectors:
        if len(vector) != config.embedding_dimensions or not all(math.isfinite(v) for v in vector):
            raise ValueError("嵌入向量维度不正确或包含非有限值")
        if not any(vector):
            raise ValueError("嵌入向量不能全为零")
    with connect() as connection:
        register_vector(connection)
        check_embedding_configuration(connection)
        inserted = connection.execute(
            "INSERT INTO rag_documents (document_hash, filename, chunk_count) "
            "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING RETURNING document_hash",
            (document_hash, filename, len(chunks)),
        ).fetchone()
        if inserted is None:
            return False
        rows = [
            (uuid5(NAMESPACE_URL, f"{document_hash}:{index}"), document_hash, text,
             Vector(vector), Jsonb({**metadata, "chunk_index": index}))
            for index, (text, vector) in enumerate(zip(chunks, vectors))
        ]
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO rag_chunks (id, document_hash, content, embedding, metadata) "
                "VALUES (%s, %s, %s, %s, %s)", rows,
            )
    return True


if __name__ == "__main__":
    init_database()
    print("PostgreSQL vector schema ready")
