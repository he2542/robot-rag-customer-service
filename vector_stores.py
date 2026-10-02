"""LangChain retrieval backed by PostgreSQL + pgvector."""

from functools import lru_cache

from langchain_postgres import PGEngine, PGVectorStore

import config_data as config
from database import check_embedding_configuration


@lru_cache(maxsize=1)
def get_pg_engine() -> PGEngine:
    if not config.database_url:
        raise ValueError("DATABASE_URL must be configured")
    return PGEngine.from_connection_string(
        config.database_url, pool_size=2, max_overflow=2,
        pool_timeout=10, pool_pre_ping=True, connect_args={"connect_timeout": 5},
    )


class VectorStoreService:
    def __init__(self, embedding):
        self.embedding = embedding
        check_embedding_configuration()
        self.vector_store = PGVectorStore.create_sync(
            engine=get_pg_engine(), table_name="rag_chunks",
            embedding_service=embedding, id_column="id", content_column="content",
            embedding_column="embedding", metadata_columns=["document_hash"],
            metadata_json_column="metadata",
        )

    def get_retriever(self):
        return self.vector_store.as_retriever(search_kwargs={"k": config.similarity_threshold})
