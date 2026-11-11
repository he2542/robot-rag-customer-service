import json

import httpx
import pytest
from langchain_core.documents import Document

from src import config
from src.services.rerank import Reranker
from src.services.retrieval import InternalKnowledgeRetriever
from src.services.rag import RagService
from langchain_core.runnables import RunnableLambda


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "private-test-key")
    monkeypatch.setattr(config, "rerank_enabled", False)
    monkeypatch.setattr(config, "rerank_url", "https://example.test/rerank")
    monkeypatch.setattr(config, "rerank_timeout", 3.0)
    monkeypatch.setattr(config, "rerank_model", "qwen3-rerank")


def docs(count=6):
    return [Document(id=str(i), page_content=f"原文 {i}",
                     metadata={"source": f"资料{i}.txt", "chunk_index": i}) for i in range(count)]


def transport(payload, status=200):
    return httpx.MockTransport(lambda request: httpx.Response(status, json=payload))


def response(count=6):
    return {"output": {"results": [{"index": i, "relevance_score": i / count}
                                    for i in range(count)]}, "usage": {"total_tokens": 123}}


def test_rerank_uses_all_candidates_and_maps_original_objects():
    documents = docs()
    def handle(request):
        body = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer private-test-key"
        assert body["parameters"] == {"top_n": 6, "return_documents": False}
        assert body["input"] == {"query": "问题", "documents": [d.page_content for d in documents]}
        payload = response()
        payload["output"]["results"][0]["document"] = {"text": "不得信任提供方回传的替换正文"}
        return httpx.Response(200, json=payload)
    result = Reranker(transport=httpx.MockTransport(handle)).rerank("问题", documents)
    assert result.status == "success" and result.usage_tokens == 123
    assert [d.id for d in result.documents] == ["5", "4", "3", "2", "1", "0"]
    assert result.documents[-1] is documents[0]
    assert result.scores == sorted(result.scores, reverse=True)
    assert result.diagnostics()["reason"] is None


@pytest.mark.parametrize("results", [
    [], [{"index": 0, "relevance_score": .5}],
    [{"index": 0, "relevance_score": .5}, {"index": 0, "relevance_score": .2}],
    [{"index": -1, "relevance_score": .5}, {"index": 1, "relevance_score": .2}],
    [{"index": 2, "relevance_score": .5}, {"index": 1, "relevance_score": .2}],
    [{"index": False, "relevance_score": .5}, {"index": 1, "relevance_score": .2}],
    [{"index": 0, "relevance_score": "0.5"}, {"index": 1, "relevance_score": .2}],
    [{"index": 0, "relevance_score": True}, {"index": 1, "relevance_score": .2}],
    [{"index": 0, "relevance_score": 1.1}, {"index": 1, "relevance_score": .2}],
    [None, {"index": 1, "relevance_score": .2}],
])
def test_invalid_provider_ranking_preserves_rrf_order(results):
    documents = docs(2)
    result = Reranker(transport=transport({"output": {"results": results}})).rerank("问题", documents)
    assert result.status == "fallback" and result.reason == "invalid_response"
    assert result.documents == documents and result.scores == []


def test_nan_score_is_rejected():
    result = Reranker(transport=httpx.MockTransport(lambda _: httpx.Response(
        200, content=b'{"output":{"results":[{"index":0,"relevance_score":NaN},{"index":1,"relevance_score":0}]}}'
    ))).rerank("问题", docs(2))
    assert result.reason == "invalid_response"


def test_ties_preserve_rrf_order_and_unknown_usage_is_optional():
    payload = {"output": {"results": [{"index": 1, "relevance_score": 0},
                                       {"index": 0, "relevance_score": 0}]}, "usage": None}
    result = Reranker(transport=transport(payload)).rerank("问题", docs(2))
    assert result.status == "success" and result.usage_tokens is None
    assert [d.id for d in result.documents] == ["0", "1"]


@pytest.mark.parametrize("status", [400, 401, 429, 500, 302])
def test_http_failures_return_baseline_without_leaking_body(status, caplog):
    documents = docs(2)
    result = Reranker(transport=transport({"message": "private-test-key secret-query"}, status)).rerank(
        "secret-query", documents)
    assert result.reason == f"http_{status}" and result.documents == documents
    assert "private-test-key" not in caplog.text and "secret-query" not in caplog.text


@pytest.mark.parametrize("error,reason", [(httpx.ReadTimeout, "timeout"), (httpx.ConnectError, "transport_error")])
def test_transport_failure_does_not_retry(error, reason):
    calls = []
    def fail(request):
        calls.append(request)
        raise error("private detail")
    result = Reranker(transport=httpx.MockTransport(fail)).rerank("问题", docs(2))
    assert result.reason == reason and len(calls) == 1


@pytest.mark.parametrize("payload", [None, [], {"output": None}, {"code": "InvalidApiKey", "message": "secret"}])
def test_bad_payload_falls_back(payload):
    assert Reranker(transport=transport(payload)).rerank("问题", docs(2)).status == "fallback"


@pytest.mark.parametrize("endpoint", ["http://example.test/rerank", "https://user:password@example.test", "https://[bad", "https://example.test:wrong", "https://example.test/?token=secret"])
def test_unsafe_endpoint_skips_request(endpoint, monkeypatch):
    monkeypatch.setattr(config, "rerank_url", endpoint)
    assert Reranker().rerank("问题", docs(2)).reason == "invalid_endpoint"


def test_budget_missing_key_and_trivial_inputs_skip_network(monkeypatch):
    assert Reranker().rerank("问题", []).status == "skipped"
    assert Reranker().rerank("问题", docs(1)).status == "skipped"
    assert Reranker().rerank("中" * 1334, docs(2)).reason == "input_budget"
    assert Reranker().rerank("a" * 4000, docs(31)).reason == "input_budget"
    duplicated = docs(2)
    duplicated[1].id = duplicated[0].id
    assert Reranker().rerank("问题", duplicated).reason == "invalid_candidates"
    monkeypatch.delenv("DASHSCOPE_API_KEY")
    assert Reranker().rerank("问题", docs(2)).reason == "not_configured"


def test_rerank_runs_before_top_four_and_only_for_enabled_hybrid(monkeypatch):
    documents = docs()
    reranker = Reranker(transport=transport(response()))
    retriever = InternalKnowledgeRetriever(None, reranker)
    monkeypatch.setattr(retriever, "rankings", lambda *_: {mode: documents for mode in ["vector", "keyword", "hybrid"]})
    assert [d.id for d in retriever.search("问题", "hybrid")] == ["0", "1", "2", "3"]
    monkeypatch.setattr(config, "rerank_enabled", True)
    assert [d.id for d in retriever.search("问题", "hybrid")] == ["5", "4", "3", "2"]
    assert [d.id for d in retriever.search("问题", "vector")] == ["0", "1", "2", "3"]
    assert [d.id for d in retriever.search("问题", "keyword")] == ["0", "1", "2", "3"]


def test_generation_and_public_sources_use_final_reranked_documents(monkeypatch):
    monkeypatch.setattr(config, "rerank_enabled", True)
    retriever = InternalKnowledgeRetriever(None, Reranker(transport=transport(response())))
    monkeypatch.setattr(retriever, "rankings", lambda *_: {"hybrid": docs()})
    monkeypatch.setattr(config, "retrieval_mode", "hybrid")
    service = RagService(retriever, RunnableLambda(lambda _: "unused"))
    captured = []
    class Chain:
        def stream(self, value, config):
            captured.extend(value["documents"])
            yield "回答[S1]"
    service.chain = Chain()
    events = list(service.stream_answer("普通问题", "test"))
    assert [d.id for d in captured] == ["5", "4", "3", "2"]
    assert events[0]["sources"][0] == {"id": "S1", "filename": "资料5.txt", "chunk_index": 5, "excerpt": "原文 5"}
