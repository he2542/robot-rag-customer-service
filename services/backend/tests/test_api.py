from fastapi.testclient import TestClient
import pytest

from src.main import app
from src import dependencies
from src.routes import health as health_router


client = TestClient(app)


@pytest.fixture(autouse=True)
def ready_knowledge(monkeypatch):
    monkeypatch.setattr(dependencies, "internal_knowledge_status", lambda: {
        "ready": True, "files": [], "chunk_count": 0, "scope_note": "示例资料",
    })


def test_health_check(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setattr(health_router, "database_ready", lambda: True)
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model_configured": False,
                               "storage_backend": "postgresql+pgvector", "database_ready": True,
                               "knowledge_ready": True}


def test_health_reports_database_failure(monkeypatch):
    monkeypatch.setattr(health_router, "database_ready", lambda: False)
    response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json()["database_ready"] is False


def test_unconfigured_chat_returns_503(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    response = client.post("/api/chat", json={"input": "hello", "session_id": "test"})
    assert response.status_code == 503


def test_session_id_rejects_path_traversal():
    response = client.post("/api/chat", json={"input": "hello", "session_id": "../../etc/passwd"})
    assert response.status_code == 422


def test_public_upload_removed():
    response = client.post(
        "/api/knowledge/upload",
        headers={"X-Filename": "knowledge.pdf"},
        content=b"not a txt file",
    )

    assert response.status_code == 404


def test_chat_requires_imported_knowledge(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-only-not-a-real-key")
    monkeypatch.setattr(dependencies, "internal_knowledge_status", lambda: {"ready": False})
    response = client.post("/api/chat", json={"input": "如何维护？"})
    assert response.status_code == 503
    assert "导入" in response.json()["detail"]


def test_chat_sources_and_content_stream(monkeypatch):
    class FakeRag:
        def stream_answer(self, query, session_id):
            yield {"sources": [{"id": 1, "filename": "维护保养.txt", "chunk_index": 0, "excerpt": "清理主刷。"}]}
            yield {"content": "请清理主刷。[1]"}
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-only-not-a-real-key")
    monkeypatch.setattr(dependencies, "get_rag_service", lambda: FakeRag())
    response = client.post("/api/chat", json={"input": "如何维护？", "session_id": "test"})
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert '"sources"' in response.text and "维护保养.txt" in response.text
    assert "请清理主刷。" in response.text and response.text.endswith("data: [DONE]\n\n")


def test_chat_failure_does_not_expose_credentials(monkeypatch):
    class BrokenRag:
        def stream_answer(self, query, session_id):
            raise RuntimeError("postgresql://private:secret@internal")
            yield
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-only-not-a-real-key")
    monkeypatch.setattr(dependencies, "get_rag_service", lambda: BrokenRag())
    response = client.post("/api/chat", json={"input": "如何维护？"})
    assert "error" in response.text and "secret" not in response.text
    assert "[DONE]" not in response.text


def test_whitespace_question_rejected(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-only-not-a-real-key")
    assert client.post("/api/chat", json={"input": "   "}).status_code == 400
