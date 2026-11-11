"""Integration checks run against a separate disposable PostgreSQL database."""

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from langchain_core.embeddings import Embeddings

from src import config
from src.database import connection as database
from src.database.schema import init_database
from src.crud import knowledge as repository
from src.services.retrieval import internal_knowledge_status
from src.services.ingestion import KnowledgeBaseService
from src.services.retrieval import InternalKnowledgeRetriever

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    not os.environ.get("RAG_RUN_DB_TESTS"), reason="requires an isolated test database"
)]


class StubEmbeddings(Embeddings):
    def __init__(self):
        self.batch_sizes = []

    def embed_query(self, text):
        return ([1.0, 0.0] if "电池" in text else [0.0, 1.0]) + [0.0] * (config.embedding_dimensions - 2)

    def embed_documents(self, texts):
        self.batch_sizes.append(len(texts))
        return [self.embed_query(text) for text in texts]


@pytest.fixture(autouse=True)
def isolated_database():
    # Refuse destructive fixture cleanup unless pointed at the dedicated test DB.
    from urllib.parse import urlsplit
    assert urlsplit(config.database_url).path.lstrip("/") in {"robot_rag_test", "robot_rag_test_internal_20261107"}
    init_database()
    with database.connect() as connection:
        connection.execute("TRUNCATE rag_documents CASCADE")
    yield
    with database.connect() as connection:
        connection.execute("TRUNCATE rag_documents CASCADE")


def counts():
    with database.connect() as connection:
        return connection.execute(
            "SELECT (SELECT count(*) FROM rag_documents), (SELECT count(*) FROM rag_chunks)"
        ).fetchone()


def test_upload_retrieve_and_deduplicate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "INTERNAL_KNOWLEDGE_DIR", tmp_path)
    (tmp_path / "电池.txt").write_text("电池保修一年。", encoding="utf-8")
    (tmp_path / "拖布.txt").write_text("拖布可拆卸清洗。", encoding="utf-8")
    embedding = StubEmbeddings()
    service = KnowledgeBaseService(embedding)
    service.upload_by_str("电池保修一年。", "电池.txt", internal=True)
    service.upload_by_str("拖布可拆卸清洗。", "拖布.txt", internal=True)
    result = InternalKnowledgeRetriever(embedding).invoke("电池保修多久？")
    assert result[0].page_content == "电池保修一年。"
    assert result[0].metadata["source"] == "电池.txt"
    assert "跳过" in service.upload_by_str("电池保修一年。", "电池.txt", internal=True)
    assert counts() == (2, 2)


def test_embedding_failure_does_not_leave_dedup_record():
    class FailedEmbeddings(StubEmbeddings):
        def embed_documents(self, texts):
            raise RuntimeError("simulated embedding failure")
    with pytest.raises(RuntimeError):
        KnowledgeBaseService(FailedEmbeddings()).upload_by_str("电池资料", "test.txt")
    assert counts() == (0, 0)
    assert "成功" in KnowledgeBaseService(StubEmbeddings()).upload_by_str("电池资料", "test.txt")


def test_database_failure_rolls_back_document_and_chunks():
    # PostgreSQL text fields reject NUL; the document ledger must roll back too.
    with pytest.raises(Exception):
        repository.insert_document("invalid", "test.txt", ["valid", "invalid\0text"],
                                 StubEmbeddings().embed_documents(["valid", "invalid"]), {})
    assert counts() == (0, 0)


def test_concurrent_upload_has_one_document():
    content = "电池资料"
    digest = hashlib.sha256(content.encode()).hexdigest()
    vector = StubEmbeddings().embed_query(content)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: repository.insert_document(
            digest, "test.txt", [content], [vector], {}), range(2)))
    assert sorted(results) == [False, True]
    assert counts() == (1, 1)


def test_incompatible_embedding_dimensions_rejected():
    with pytest.raises(ValueError, match="维度"):
        repository.insert_document("bad-dim", "test.txt", ["text"], [[1.0, 0.0]], {})
    assert counts() == (0, 0)


def test_model_change_rejected(monkeypatch):
    monkeypatch.setattr(config, "embedding_model_name", "different-model")
    with pytest.raises(ValueError, match="不匹配"):
        database.check_embedding_configuration()


def test_upload_batches_at_most_ten_chunks():
    embedding = StubEmbeddings()
    service = KnowledgeBaseService(embedding)
    service.upload_by_str("电池资料。" * 3000, "long.txt")
    assert len(embedding.batch_sizes) > 1
    assert max(embedding.batch_sizes) <= 10


@pytest.mark.parametrize("mode", ["vector", "keyword", "hybrid"])
def test_internal_retrieval_excludes_uploads_and_superseded_versions(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(config, "retrieval_mode", mode)
    monkeypatch.setattr(config, "INTERNAL_KNOWLEDGE_DIR", tmp_path)
    source = tmp_path / "电池.txt"
    source.write_text("电池维护旧版资料。", encoding="utf-8")
    embedding = StubEmbeddings()
    service = KnowledgeBaseService(embedding)
    service.upload_by_str("电池维护旧版资料。", source.name, internal=True)
    service.upload_by_str("电池保修虚构政策，不能混入内部问答。", "历史上传.txt")
    retriever = InternalKnowledgeRetriever(embedding)
    assert internal_knowledge_status()["ready"] is True
    assert [doc.page_content for doc in retriever.invoke("电池")] == ["电池维护旧版资料。"]
    assert "跳过" in service.upload_by_str("电池维护旧版资料。", source.name, internal=True)

    source.write_text("电池维护新版资料。", encoding="utf-8")
    assert internal_knowledge_status()["ready"] is False
    assert retriever.invoke("电池") == []
    service.upload_by_str("电池维护新版资料。", source.name, internal=True)
    assert internal_knowledge_status()["ready"] is True
    assert [doc.page_content for doc in retriever.invoke("电池")] == ["电池维护新版资料。"]
    assert counts() == (3, 3)  # Historical rows are preserved but excluded from retrieval.
