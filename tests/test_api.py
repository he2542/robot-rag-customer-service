from fastapi.testclient import TestClient

from api import app
import api


client = TestClient(app)


def test_health_check(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setattr(api, "database_ready", lambda: True)
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model_configured": False,
                               "storage_backend": "postgresql+pgvector", "database_ready": True}


def test_health_reports_database_failure(monkeypatch):
    monkeypatch.setattr(api, "database_ready", lambda: False)
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


def test_upload_rejects_non_txt_files():
    response = client.post(
        "/api/knowledge/upload",
        headers={"X-Filename": "knowledge.pdf"},
        content=b"not a txt file",
    )

    assert response.status_code == 400
    assert "TXT" in response.json()["detail"]
