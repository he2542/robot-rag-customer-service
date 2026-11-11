"""Query embedding and document adaptation for the managed corpus."""
import math
from threading import Lock
import psycopg
from langchain_core.documents import Document
from src import config
from .corpus import KNOWLEDGE_BASE, SCOPE_NOTE, load_internal_files
from src.crud.knowledge import nearest_chunks, chunk_counts, scoped_chunks
from .keyword import KeywordIndex


def as_documents(rows) -> list[Document]:
    return [Document(id=str(chunk_id), page_content=content,
                     metadata={**metadata, "document_hash": digest})
            for content, metadata, digest, chunk_id in rows]


def reciprocal_rank_fusion(rankings: list[list[Document]], limit: int,
                           constant: int = 60) -> list[Document]:
    """Equal-weight RRF; duplicates within a route count once."""
    if constant < 1 or limit < 1:
        raise ValueError("RRF constant and limit must be positive")
    scores, documents = {}, {}
    for ranking in rankings:
        seen = set()
        for rank, document in enumerate(ranking, 1):
            if not document.id:
                raise ValueError("RRF requires a stable chunk ID")
            if document.id in seen:
                continue
            seen.add(document.id)
            documents.setdefault(document.id, document)
            scores[document.id] = scores.get(document.id, 0.0) + 1.0 / (constant + rank)
    ordered = sorted(scores, key=lambda key: (-scores[key], key))
    return [documents[key] for key in ordered[:limit]]


class InternalKnowledgeRetriever:
    def __init__(self, embedding):
        self.embedding = embedding
        self._keyword_lock = Lock()
        self._keyword_signature = None
        self._keyword_index = None

    def invoke(self, query: str) -> list[Document]:
        return self.search(query)

    def search(self, query: str, mode: str | None = None) -> list[Document]:
        mode = config.retrieval_mode if mode is None else mode
        if mode not in {"vector", "keyword", "hybrid"}:
            raise ValueError("Unknown retrieval mode")
        return self.rankings(query, mode)[mode][:config.retrieval_top_k]

    def rankings(self, query: str, mode: str = "hybrid") -> dict[str, list[Document]]:
        """Internal diagnostics for evaluation, never exposed as a public route."""
        if mode not in {"vector", "keyword", "hybrid"}:
            raise ValueError("Unknown retrieval mode")
        if len(query) > 4000:
            raise ValueError("Query must not exceed 4000 characters")
        if not query.strip():
            return {"vector": [], "keyword": [], "hybrid": []}
        files = load_internal_files()
        hashes = [file.document_hash for file in files]
        vector_documents = self._vector_search(query, hashes) if mode != "keyword" else []
        keyword_documents = self._keyword_search(query, hashes) if mode != "vector" else []
        fused = (reciprocal_rank_fusion([vector_documents, keyword_documents],
                                       config.retrieval_candidate_k * 2, config.retrieval_rrf_k)
                 if mode == "hybrid" else [])
        return {"vector": vector_documents, "keyword": keyword_documents, "hybrid": fused}

    def _vector_search(self, query, hashes):
        vector = self.embedding.embed_query(query)
        if (len(vector) != config.embedding_dimensions
                or not all(math.isfinite(value) for value in vector) or not any(vector)):
            raise ValueError("查询向量维度或数值无效")
        return as_documents(nearest_chunks(hashes, KNOWLEDGE_BASE, vector,
                                          config.retrieval_candidate_k))

    def _keyword_search(self, query, hashes):
        # Query the database each time: an import completing under unchanged file
        # hashes must invalidate a previously empty/partial cached index too.
        rows = scoped_chunks(hashes, KNOWLEDGE_BASE)
        signature = tuple((str(row[3]), row[0]) for row in rows)
        with self._keyword_lock:
            if signature != self._keyword_signature:
                self._keyword_index = KeywordIndex(as_documents(rows))
                self._keyword_signature = signature
            index = self._keyword_index
        return index.search(query, config.retrieval_candidate_k)

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
