"""Control-plane endpoint response tests (prompts, workflows, telemetry, OpenAPI)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_openapi_available(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    assert spec["info"]["title"]
    paths = spec["paths"]
    assert "/auth/login" in paths
    assert "/auth/refresh" in paths
    assert "/auth/me" in paths
    assert "/prompts/review" in paths
    assert "/prompts" in paths
    assert "/workflows/review" in paths
    assert "/workflows" in paths
    assert "/config" in paths
    assert "/config/bundle" in paths
    assert "/organizations/{organization_id}" in paths
    assert "/repositories/{repository_id}" in paths
    assert "/telemetry" in paths


def test_docs_ui(client: TestClient) -> None:
    response = client.get("/docs")
    assert response.status_code == 200


def test_prompts_review_requires_auth(client: TestClient) -> None:
    assert client.get("/prompts/review").status_code == 401


def test_prompts_review_static_payload(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/prompts/review", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "review"
    assert body["version"]
    assert "{{repository_name}}" in body["template"]
    assert "repository_name" in body["variables"]


def test_workflows_review_static_payload(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/workflows/review", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "review"
    assert isinstance(body["steps"], list)
    assert len(body["steps"]) >= 1
    assert body["feature_flags"]["telemetry_enabled"] is True
    assert body["metadata"]["execution_location"] == "cli"


def test_telemetry_accepts_metadata(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/telemetry",
        headers=auth_headers,
        json={
            "event_type": "cli.command",
            "cli_version": "0.1.0",
            "os_name": "Windows",
            "message": "search completed",
            "payload": {"command": "search", "duration_ms": 120},
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["accepted"] is True
    assert body["event_type"] == "cli.command"
    assert body["id"] >= 1


def test_telemetry_rejects_source_code_keys(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/telemetry",
        headers=auth_headers,
        json={
            "event_type": "cli.command",
            "payload": {"source_code": "print('nope')"},
        },
    )
    assert response.status_code == 422


def test_telemetry_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/telemetry",
        json={"event_type": "cli.command", "payload": {}},
    )
    assert response.status_code == 401
