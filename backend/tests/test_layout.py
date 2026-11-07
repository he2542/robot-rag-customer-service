"""Regression checks for the src-layout migration and application composition."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

from fastapi.testclient import TestClient
from robot_rag import config, main
from robot_rag.dependencies import get_chat_service
from robot_rag.modules.rag.service import internal_history


BACKEND = Path(__file__).resolve().parents[1]


def test_old_api_entry_exports_same_application():
    assert runpy.run_path(str(BACKEND / "api.py"))["app"] is main.app
    assert config.PROJECT_ROOT == BACKEND


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

    app.dependency_overrides[get_chat_service] = lambda: FakeChat()
    with TestClient(app) as client:
        assert client.get("/").text == "<h1>RAG</h1>"
        assert client.post("/api/knowledge/upload", content=b"unused").status_code == 404
        response = client.post("/api/chat", json={"input": "hello"})
        assert '"content": "hello"' in response.text
        assert response.text.endswith("data: [DONE]\n\n")


def test_import_preview_entrypoints_work_outside_backend(tmp_path):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    results = []
    for script in (BACKEND / "import_knowledge.py", BACKEND / "scripts/import_knowledge.py"):
        output = subprocess.run([sys.executable, str(script)], cwd=tmp_path,
                                env=env, capture_output=True, encoding="utf-8", check=True)
        results.append(json.loads(output.stdout))
    assert results[0] == results[1]
    assert results[0]["mode"] == "preview"
    assert len(results[0]["files"]) == 5
    assert results[0]["total_chunks"] == 63
