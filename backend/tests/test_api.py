import io

from fastapi.testclient import TestClient

from app.api import app

client = TestClient(app)

JSON_LOG = "\n".join(
    f'{{"timestamp":"2026-01-14T09:{i:02d}:00Z","level":"info","message":"request {i}"}}'
    for i in range(20)
)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_analyse_text():
    response = client.post("/api/analyse", json={"text": JSON_LOG})
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["detected_format"] == "json"
    assert body["summary"]["parsed_lines"] == 20
    assert "timeline" in body and "patterns" in body


def test_analyse_rejects_empty_text():
    assert client.post("/api/analyse", json={"text": "   "}).status_code == 422


def test_analyse_validates_limits():
    response = client.post("/api/analyse", json={"text": JSON_LOG, "max_entries": 0})
    assert response.status_code == 422


def test_upload_file():
    files = {"file": ("app.log", io.BytesIO(JSON_LOG.encode()), "text/plain")}
    response = client.post("/api/upload", files=files)
    assert response.status_code == 200
    assert response.json()["summary"]["parsed_lines"] == 20


def test_upload_rejects_empty_file():
    files = {"file": ("empty.log", io.BytesIO(b"   "), "text/plain")}
    assert client.post("/api/upload", files=files).status_code == 422


def test_upload_handles_invalid_utf8():
    files = {"file": ("bin.log", io.BytesIO(b"\xff\xfe bad bytes \n INFO ok"), "text/plain")}
    assert client.post("/api/upload", files=files).status_code == 200


def test_sample_endpoint_returns_an_incident():
    response = client.get("/api/sample?lines=800")
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["parsed_lines"] > 700
    assert len(body["anomalies"]) > 0


def test_sample_line_count_is_clamped():
    assert client.get("/api/sample?lines=1").json()["summary"]["parsed_lines"] >= 50


def test_sample_raw():
    body = client.get("/api/sample/raw?lines=100").json()
    assert body["text"].count("\n") == 99


def test_openapi_schema_is_generated():
    schema = client.get("/openapi.json").json()
    assert "/api/analyse" in schema["paths"]
    assert "/api/upload" in schema["paths"]
