"""Knowledge persistence. All values in queries are parameterized."""
import math
from uuid import NAMESPACE_URL, uuid5
from pgvector.psycopg import Vector, register_vector
from psycopg.types.json import Jsonb
from src import config
from src.database.connection import connect, check_embedding_configuration
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


def chunk_counts(document_hashes: list[str], knowledge_base: str) -> dict[str, int]:
    with connect() as connection:
        check_embedding_configuration(connection)
        rows = connection.execute(
            "SELECT document_hash, count(*) FROM rag_chunks "
            "WHERE document_hash = ANY(%s) AND metadata->>'knowledge_base' = %s "
            "GROUP BY document_hash", (document_hashes, knowledge_base),
        ).fetchall()
    return dict(rows)


def nearest_chunks(document_hashes, knowledge_base, vector, limit):
    with connect() as connection:
        register_vector(connection)
        check_embedding_configuration(connection)
        return connection.execute(
            "WITH candidates AS MATERIALIZED ("
            "SELECT content, metadata, embedding, document_hash FROM rag_chunks "
            "WHERE document_hash = ANY(%s) AND metadata->>'knowledge_base' = %s) "
            "SELECT content, metadata, document_hash FROM candidates "
            "ORDER BY embedding <=> %s LIMIT %s",
            (document_hashes, knowledge_base, Vector(vector), limit),
        ).fetchall()
