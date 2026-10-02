"""Split and embed knowledge files, then commit them atomically to PostgreSQL."""

import hashlib
from datetime import datetime, timezone

from langchain_community.embeddings import DashScopeEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config_data as config
from database import check_embedding_configuration, document_exists, insert_document


class KnowledgeBaseService:
    def __init__(self, embedding=None):
        check_embedding_configuration()
        self.embedding = embedding if embedding is not None else DashScopeEmbeddings(
            model=config.embedding_model_name
        )
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size, chunk_overlap=config.chunk_overlap,
            separators=["\n\n", "\n", "。", ".", " ", ""], length_function=len,
        )

    def upload_by_str(self, data: str, filename: str) -> str:
        if not data.strip():
            raise ValueError("文件内容不能为空")
        document_hash = hashlib.sha256(data.encode("utf-8")).hexdigest()
        if document_exists(document_hash):
            return "[跳过]，内容已存在知识库中"
        chunks = self.splitter.split_text(data)
        vectors = []
        # text-embedding-v4 accepts up to 10 texts per request.
        for offset in range(0, len(chunks), 10):
            batch = chunks[offset:offset + 10]
            embedded = self.embedding.embed_documents(batch)
            if len(embedded) != len(batch):
                raise ValueError("嵌入模型返回数量与文本片段数量不一致")
            vectors.extend(embedded)
        metadata = {
            "source": filename, "create_time": datetime.now(timezone.utc).isoformat(),
            "embedding_model": config.embedding_model_name,
        }
        inserted = insert_document(document_hash, filename, chunks, vectors, metadata)
        return "[成功]内容已经成功载入向量库" if inserted else "[跳过]，内容已存在知识库中"

    def upload_text(self, data: str, filename: str) -> str:
        return self.upload_by_str(data, filename)
