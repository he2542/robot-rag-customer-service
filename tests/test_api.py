from fastapi.testclient import TestClient

from api import app


client = TestClient(app)


def test_health_check():
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_upload_rejects_non_txt_files():
    response = client.post(
        "/api/knowledge/upload",
        headers={"X-Filename": "knowledge.pdf"},
        content=b"not a txt file",
    )

    assert response.status_code == 400
    assert "TXT" in response.json()["detail"]
