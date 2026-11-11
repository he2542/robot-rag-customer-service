from concurrent.futures import ThreadPoolExecutor

import pytest
from langchain_core.documents import Document

from src import config
from src.services import retrieval
from src.services.keyword import KeywordIndex, tokenize


def doc(key, text):
    return Document(id=key, page_content=text)


def test_chinese_tokenization_and_identifier_normalization():
    assert "充电" in tokenize("请问充电触点怎么清洁？")
    assert tokenize("ＷＩＦＩ ２.４Ｇ H13 E-01") == ["wifi", "2.4g", "h13", "e-01"]
    assert tokenize("呢？的！") == []


def test_bm25_matches_identifiers_without_padding_unmatched_chunks():
    index = KeywordIndex([doc("a", "WiFi 2.4G 连接"), doc("b", "H13 滤网"), doc("c", "拖布清洗")])
    assert [d.id for d in index.search("２.４Ｇ", 10)] == ["a"]
    assert index.search("zxq987", 10) == []
    assert index.search("！？", 10) == []
    assert KeywordIndex([]).search("电池", 10) == []


def test_common_terms_with_nonpositive_bm25_scores_are_still_matches():
    index = KeywordIndex([doc("a", "电池"), doc("b", "电池")])
    assert [d.id for d in index.search("电池", 10)] == ["a", "b"]


def test_rrf_combines_routes_once_per_id_and_breaks_ties_stably():
    a, b, c = doc("a", "a"), doc("b", "b"), doc("c", "c")
    fused = retrieval.reciprocal_rank_fusion([[a, a, b], [b, c]], 4)
    assert [d.id for d in fused] == ["b", "a", "c"]
    assert [d.id for d in retrieval.reciprocal_rank_fusion([[b], [a]], 4)] == ["a", "b"]
    with pytest.raises(ValueError, match="stable chunk ID"):
        retrieval.reciprocal_rank_fusion([[Document(page_content="no id")]], 4)


class Embedding:
    def __init__(self):
        self.calls = 0

    def embed_query(self, query):
        self.calls += 1
        return [1.0] + [0.0] * (config.embedding_dimensions - 1)


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    (tmp_path / "资料.txt").write_text("电池和拖布", encoding="utf-8")
    monkeypatch.setattr(config, "INTERNAL_KNOWLEDGE_DIR", tmp_path)


def test_keyword_index_refreshes_after_import_and_content_change(corpus, monkeypatch):
    rows = []
    monkeypatch.setattr(retrieval, "scoped_chunks", lambda *_: list(rows))
    retriever = retrieval.InternalKnowledgeRetriever(Embedding())
    assert retriever.search("电池", "keyword") == []
    rows.append(("电池", {}, "current-hash", "a"))
    assert retriever.search("电池", "keyword")[0].id == "a"
    cached = retriever._keyword_index
    retriever.search("电池", "keyword")
    assert retriever._keyword_index is cached
    rows[0] = ("拖布", {}, "current-hash", "a")
    assert retriever.search("电池", "keyword") == []
    assert retriever._keyword_index is not cached
    assert retriever.embedding.calls == 0


def test_concurrent_keyword_queries_use_consistent_snapshot(corpus, monkeypatch):
    monkeypatch.setattr(retrieval, "scoped_chunks", lambda *_: [("电池", {}, "hash", "a")])
    retriever = retrieval.InternalKnowledgeRetriever(Embedding())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: retriever.search("电池", "keyword")[0].id, range(12)))
    assert results == ["a"] * 12


def test_empty_keyword_route_preserves_vector_order_and_vector_mode_skips_bm25(corpus, monkeypatch):
    monkeypatch.setattr(retrieval, "nearest_chunks", lambda *_: [("电池", {}, "hash", "a")])
    monkeypatch.setattr(retrieval, "scoped_chunks", lambda *_: [])
    retriever = retrieval.InternalKnowledgeRetriever(Embedding())
    assert retriever.search("电池", "hybrid")[0].id == "a"
    def must_not_read(*_):
        raise AssertionError("vector mode must not read BM25 corpus")
    monkeypatch.setattr(retrieval, "scoped_chunks", must_not_read)
    assert retriever.search("电池", "vector")[0].id == "a"


def test_invalid_and_blank_queries_do_not_call_embedding():
    retriever = retrieval.InternalKnowledgeRetriever(Embedding())
    assert retriever.invoke("  ") == []
    with pytest.raises(ValueError):
        retriever.invoke("a" * 4001)
    with pytest.raises(ValueError):
        retriever.search("问题", "unknown")
    assert retriever.embedding.calls == 0


def test_database_error_is_not_silently_turned_into_keyword_miss(corpus, monkeypatch):
    def unavailable(*_):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(retrieval, "scoped_chunks", unavailable)
    with pytest.raises(RuntimeError, match="database unavailable"):
        retrieval.InternalKnowledgeRetriever(Embedding()).search("电池", "keyword")


@pytest.mark.parametrize("vector", [[0.0] * 1024, [float("nan")] * 1024, [1.0]])
def test_invalid_embedding_never_reaches_sql(corpus, monkeypatch, vector):
    embedding = Embedding()
    embedding.embed_query = lambda _: vector
    def must_not_query(*_):
        raise AssertionError("invalid vector reached database")
    monkeypatch.setattr(retrieval, "nearest_chunks", must_not_query)
    with pytest.raises(ValueError, match="查询向量"):
        retrieval.InternalKnowledgeRetriever(embedding).search("电池", "vector")
