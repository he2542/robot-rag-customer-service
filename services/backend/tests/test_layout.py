"""Regression checks for the src-layout migration and application composition."""
import json
import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
from src import config, main
from src.dependencies import get_rag_factory, get_knowledge_status
from src.services.rag import internal_history


BACKEND = Path(__file__).resolve().parents[1]


def test_backend_and_corpus_paths():
    assert config.PROJECT_ROOT == BACKEND
    assert config.REPOSITORY_ROOT == BACKEND.parents[1]
    assert config.INTERNAL_KNOWLEDGE_DIR == config.REPOSITORY_ROOT / "knowledge/robot"


def test_history_keeps_previous_namespace(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    assert Path(internal_history("layout-test").file_path) == tmp_path / "chat_history/robot_internal_v1/layout-test"


def test_static_frontend_and_dependency_override(tmp_path, monkeypatch):
    backend = tmp_path / "backend"
    dist = tmp_path / "frontend/dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<h1>RAG</h1>", encoding="utf-8")
    monkeypatch.setattr(main, "PROJECT_ROOT", backend)
    monkeypatch.setenv("RAG_SERVE_FRONTEND", "1")
    app = main.create_app()

    class FakeChat:
        def prepare(self, text):
            return text.strip()

        def stream_answer(self, query, session_id):
            yield {"sources": []}
            yield {"content": query}

    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-only-not-a-real-key")
    app.dependency_overrides[get_rag_factory] = lambda: lambda: FakeChat()
    app.dependency_overrides[get_knowledge_status] = lambda: {"ready": True}
    with TestClient(app) as client:
        assert client.get("/").text == "<h1>RAG</h1>"
        assert client.post("/api/knowledge/upload", content=b"unused").status_code == 404
        response = client.post("/api/chat", json={"input": "hello"})
        assert '"content": "hello"' in response.text
        assert response.text.endswith("data: [DONE]\n\n")


def test_single_cli_entry_previews_corpus(tmp_path):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(BACKEND)}
    output = subprocess.run([sys.executable, "-m", "src.cli", "import-knowledge"], cwd=tmp_path,
                            env=env, capture_output=True, encoding="utf-8", check=True)
    result = json.loads(output.stdout)
    assert result["mode"] == "preview"
    assert len(result["files"]) == 5
    assert result["total_chunks"] == 63
