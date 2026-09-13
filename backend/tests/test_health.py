from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_contract() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"] in {"ok", "unavailable"}


def test_versioned_health_route() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200


def test_error_contract() -> None:
    response = client.get("/missing")

    assert response.status_code == 404
    assert set(response.json()) == {"error", "detail", "status_code"}
