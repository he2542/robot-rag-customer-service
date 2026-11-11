"""Query embedding and document adaptation for the managed corpus."""
import math
import psycopg
from langchain_core.documents import Document
from src import config
from .corpus import KNOWLEDGE_BASE, SCOPE_NOTE, load_internal_files
from src.crud.knowledge import nearest_chunks, chunk_counts


class InternalKnowledgeRetriever:
    def __init__(self, embedding):
        self.embedding = embedding

    def invoke(self, query: str) -> list[Document]:
        files = load_internal_files()
        vector = self.embedding.embed_query(query)
        if (len(vector) != config.embedding_dimensions
                or not all(math.isfinite(value) for value in vector) or not any(vector)):
            raise ValueError("查询向量维度或数值无效")
        rows = nearest_chunks([file.document_hash for file in files], KNOWLEDGE_BASE,
                              vector, config.retrieval_top_k)
        return [Document(page_content=content, metadata={**metadata, "document_hash": digest})
                for content, metadata, digest in rows]

def internal_knowledge_status() -> dict:
    try:
        files = load_internal_files()
        counts = chunk_counts([file.document_hash for file in files], KNOWLEDGE_BASE)
        items = [{"filename": file.filename, "chunks": counts.get(file.document_hash, 0)}
                 for file in files]
        return {"ready": all(item["chunks"] > 0 for item in items),
                "files": items, "chunk_count": sum(counts.values()), "scope_note": SCOPE_NOTE}
    except (OSError, UnicodeError, psycopg.Error, ValueError):
        return {"ready": False, "files": [], "chunk_count": 0, "scope_note": SCOPE_NOTE}
