"""Query embedding and document adaptation for the managed corpus."""
import math
from langchain_core.documents import Document
from robot_rag import config
from .corpus import KNOWLEDGE_BASE, load_internal_files
from .repository import nearest_chunks


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
