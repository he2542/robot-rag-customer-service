"""Explicit schema initialization. Never run on application startup."""
from robot_rag import config
from robot_rag.shared.database import connect, check_embedding_configuration
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
